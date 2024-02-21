import asyncio
import datetime
from asyncio import transports
from dataclasses import dataclass, field
from itertools import cycle
from typing import Union, Callable, Any, Coroutine

from loguru import logger
from python_socks._errors import ProxyError
from python_socks._types import ProxyType
from python_socks.async_.asyncio import Proxy


def is_event_loop_set() -> bool:
    """
    check if asyncio has loop set
    :return: bool
    """
    try:
        # check if any event loop is set
        asyncio.get_event_loop()
        return True
    except RuntimeError as _error:
        return False


def get_time_difference(time_str: str) -> float:
    """
    get time difference
    :param time_str:
    :return:
    """
    now = datetime.datetime.now().time()

    # Parse the target time from the input string
    target_time = datetime.datetime.strptime(time_str, '%H:%M').time()

    # Calculate the time difference between now and the target time
    time_diff = datetime.datetime.combine(datetime.date.today(), target_time) - datetime.datetime.combine(
        datetime.date.today(), now)

    # If the target time has already passed today, calculate the time difference for tomorrow
    if time_diff.total_seconds() < 0:
        tomorrow = datetime.date.today() + datetime.timedelta(days=1)
        time_diff = datetime.datetime.combine(tomorrow, target_time) - datetime.datetime.combine(
            datetime.date.today(), now)

    return time_diff.total_seconds()


@dataclass
class CommandCallback:
    name: str
    callback: Callable
    mod_only: bool = False
    aliases: list[str] = field(default_factory=lambda: [])
    case_sensitive: bool = True


@dataclass
class Command:
    command: Union[None, str] = None
    channel: Union[None, str] = None
    channel_raw: Union[None, str] = None
    bot_command: Union[None, str] = None
    bot_command_params: Union[None, str] = None
    is_cap_request_enabled: [None, bool] = None


@dataclass
class Source:
    nick: Union[None, str] = None
    host: Union[None, str] = None


@dataclass
class Message:
    tags: Union[None, dict[str, Union[None, dict, list[str]]]] = None
    source: Union[None, Source] = None
    command: Union[None, Command] = None
    parameters: Union[None, str] = None


def parse_command(cmp) -> Union[Command, None]:
    """
    parse command component
    :param cmp: cmp
    :return: str
    """
    parsed_command: Command = Command()
    command_parts = cmp.split(' ')

    match (command_parts[0]):
        case "JOIN" | "PART" | "NOTICE" | "CLEARCHAT" | "HOSTTARGET" | "PRIVMSG" | "USERSTATE" | "ROOMSTATE" | "PONG" | "USERNOTICE":
            parsed_command.command = command_parts[0]
            parsed_command.channel_raw = command_parts[1]
            parsed_command.channel = command_parts[1][1:]

        case "CAP":
            parsed_command.command = command_parts[0]
            parsed_command.is_cap_request_enabled = command_parts[2] == "ACK"

        case "GLOBALUSERSTATE" | "PING" | "RECONNECT":
            parsed_command.command = command_parts[0]

        case "431":
            return logger.warning(f"Unsupported IRC command: {command_parts[2]}")

        case "001" | "002" | "003" | "004" | "353" | "366" | "372" | "375" | "376" | "433" | "474":
            parsed_command.command = command_parts[0]

        case _:
            return logger.error(f"\n\nUnexpected Command: {command_parts[0]} ({command_parts})\n")

    return parsed_command


def parse_tags(cmp: str) -> dict[str, Union[None, dict, list[str]]]:
    """
    parse tags
    :param cmp: str
    :return: Tags
    """
    tags_to_ignore: dict[str, Union[None, str]] = {
        "client-nonce": None,
        "flags": None
    }

    tags: dict[str, Union[None, dict, list[str]]] = {}

    split_tags: list[str] = cmp.split(';')

    for tag in split_tags:
        key_value: list[str] = tag.split('=')
        tag_value: Union[None, str] = None if key_value[1] == '' else key_value[1]

        match key_value[0]:
            case "badges" | "badge-info":
                if tag_value is not None:
                    data: dict[str, str] = {}
                    badges: list[str] = tag_value.split(',')
                    for pair in badges:
                        badge_parts: list[str] = pair.split('/')
                        data[badge_parts[0]] = badge_parts[1]
                    tags[key_value[0]] = data
                else:
                    tags[key_value[0]] = None

            case "emotes":
                if tag_value is not None:
                    data: dict = {}
                    emotes = tag_value.split('/')
                    for emote in emotes:
                        emote_parts = emote.split(':')
                        text_positions = []
                        positions = emote_parts[1].split(',')
                        for pos in positions:
                            pos_parts = pos.split('-')
                            text_positions.append(
                                {
                                    "start_position": pos_parts[0],
                                    "end_position": pos_parts[1]
                                }
                            )
                        data[emote_parts[0]] = text_positions
                    tags[key_value[0]] = data
                else:
                    tags[key_value[0]] = None

            case "emote-sets":
                emote_set_ids = tag_value.split(',')
                tags[key_value[0]] = emote_set_ids

            case _:
                if key_value[0] not in tags_to_ignore:
                    tags[key_value[0]] = tag_value

    return tags


def parse_source(cmp: str) -> Union[None, Source]:
    """
    parses source
    :param cmp: source string
    :return: Source
    """
    if cmp is None:
        return None

    source_parts: list[str] = cmp.split('!')

    return Source(
        source_parts[0] if len(source_parts) == 2 else None,
        source_parts[1] if len(source_parts) == 2 else source_parts[0]
    )


def parse_parameters(cmp: str, command: Command) -> Command:
    """
    parse parameters
    :param cmp: parameter string
    :param command: command object
    :return: Command
    """
    pointer: int = 0
    command_parts = cmp[pointer + 1].strip()
    param_pointer = command_parts.find(' ')

    if param_pointer == -1:
        command.bot_command = command_parts[:]
    else:
        command.bot_command = command_parts[:param_pointer]
        command.bot_command_params = command_parts[param_pointer:].strip()

    return command


def parse_message(message_string: str) -> Union[None, Message]:
    """
    parse message and return Message object
    :param message_string: message string
    :return: Message
    """
    message = Message()

    raw_tags_component: Union[None, str] = None
    raw_source_component = None
    _raw_command_component = None
    raw_parameter_component = None

    pointer: int = 0
    end_pointer: int

    if message_string[pointer] == '@':
        end_pointer = message_string.find(' ')
        raw_tags_component = message_string[1: end_pointer]
        pointer = end_pointer + 1

    if message_string[pointer] == ':':
        pointer += 1
        end_pointer = message_string.find(' ', pointer)
        raw_source_component = message_string[pointer: end_pointer]
        pointer = end_pointer + 1

    # command part
    end_pointer = message_string.find(':', pointer)
    if end_pointer == -1:
        end_pointer = len(message_string)

    raw_command_component = message_string[pointer: end_pointer].strip()

    # parameters
    if end_pointer < len(message_string):
        pointer = end_pointer + 1
        raw_parameter_component = message_string[pointer:]

    # parse command
    message.command = parse_command(raw_command_component)

    # discard if command is none
    if message.command is None:
        return None

    if raw_tags_component is not None:
        message.tags = parse_tags(raw_tags_component)

    message.source = parse_source(raw_source_component)
    message.parameters = raw_parameter_component

    if raw_parameter_component and raw_parameter_component[0] == '!':
        message.command = parse_parameters(raw_parameter_component, message.command)

    return message


class Timer:
    def __init__(self, timeout: int, callback: Callable):
        """
        async timer
        :param timeout: timeout
        :param callback: callback
        """
        self._timeout: int = timeout
        self._callback: Callable = callback
        self._task: Union[asyncio.Task, None] = None

    async def _wait(self) -> None:
        """
        wait until timeout has expired
        :return: None
        """
        await asyncio.sleep(self._timeout)
        await self._callback()

    def start(self) -> None:
        """
        start timer
        :return: None
        """
        loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
        self._task = loop.create_task(self._wait())

    def cancel(self) -> None:
        """
        cancel timer
        :return: None
        """
        if self._task is None:
            logger.warning("Timer has not been started yet.")
            return
        self._task.cancel()

    def restart(self) -> None:
        """
        restart timer
        :return: None
        """
        self.cancel()
        self.start()


class AsyncIRCClientProtocol(asyncio.Protocol):

    def __init__(self, on_connection_made: Union[Callable, None] = None,
                 on_connection_lost: Union[Callable, None] = None, on_data_received: Union[Callable, None] = None):
        """
        protocol constructor
        :param on_connection_made: on connection established callback
        :param on_connection_lost: on connection lost callback
        :param on_data_received: on data received callback
        """

        self._transport: Union[transports.Transport, None] = None

        self._on_connection_made_callback: Union[Callable, None] = on_connection_made
        self._on_connection_lost_callback: Union[Callable, None] = on_connection_lost
        self._on_data_received_callback: Union[Callable, None] = on_data_received

        super().__init__()

    def connection_made(self, transport: transports.Transport) -> None:
        """
        Upon connection has been established
        :param transport: base transport
        :return: None
        """
        logger.debug(f"{self} Connected.")
        self._transport = transport
        if self._on_connection_made_callback is not None:
            self._on_connection_made_callback(transport)

    def connection_lost(self, exception: Union[Exception, None]) -> None:
        """
        connecting to server has been lost
        :param exception: exception
        :return: None
        """
        logger.debug(f"{self} disconnected.")
        self._transport.close()
        if self._on_connection_made_callback is not None:
            self._on_connection_lost_callback(exception)

    def data_received(self, data: bytes) -> None:
        """
        called upon new data received from server
        :param data: data as bytes
        :return: None
        """
        if self._on_data_received_callback is not None:
            decoded_data: str = data.decode()
            message: str
            for message in decoded_data.split("\r\n"):
                if not message:
                    continue
                self._on_data_received_callback(message)

    def send_irc_data(self, data: str, log: bool = True) -> None:
        """
        send raw irc data as string
        :param data: data to send
        :param log: log sending
        :return: None
        """
        if log:
            logger.debug(f"Sending {data}")
        try:
            self._transport.write(bytes(data + "\n\r", "utf-8"))
        except Exception as error:
            logger.exception(error)


class IRCClientInterfaceMixin:
    def on_connected_to_server(self) -> None:
        """
        called as soon as the client connected to the server
        :return: None
        """

    def on_disconnected_from_server(self, exception: Exception) -> None:
        """
        called as soon as the client disconnects from the server
        :param exception: exception that caused the disconnect
        :return: None
        """


class IRCClient(IRCClientInterfaceMixin):

    def __init__(self, server: str, port: int, loop: Union[asyncio.AbstractEventLoop, None] = None,
                 proxies: list[Proxy] = None):
        """
        constructor
        :param server: server to connect to
        :param port: port to connect to
        :param loop: set custom event loop
        :param proxies: list of proxy objects to use to mask connection
        """
        self._server: str = server
        self._port: int = port
        self._loop: Union[asyncio.AbstractEventLoop, None] = loop
        self._protocol: Union[AsyncIRCClientProtocol, None] = None
        self._transport: Union[transports.Transport, None] = None
        self._event_handler: dict[str, Callable] = {}
        self._is_connected: bool = False
        self._proxies: list[Proxy] = proxies or []
        self._proxy_cycle: cycle[Proxy] = cycle(self._proxies)
        self._use_proxies: bool = len(proxies) > 0
        self._current_proxy: Proxy = None
        self._retry_delay: int = 5

        # get event loop if none set
        if self._loop is None:
            self._loop = asyncio.get_event_loop() if is_event_loop_set() else asyncio.new_event_loop()

    def add_proxy(self, proxy: Proxy) -> None:
        self._proxies.append(proxy)
        self._proxy_cycle = cycle(self._proxies)

    def remove_proxy(self, proxy: Proxy) -> None:
        self._proxies.remove(proxy)
        self._proxy_cycle = cycle(self._proxies)

    def set_proxies(self, proxies: list[Proxy]) -> None:
        self._proxies = proxies
        self._proxy_cycle = cycle(self._proxies)

    def get_proxies(self) -> list[Proxy]:
        return self._proxies

    def get_current_proxy(self) -> Proxy:
        return self._current_proxy

    def send_irc_data(self, data: str, log: bool = True) -> None:
        """
        send irc data.
        :param data: data to send
        :param log: log to console
        :return: None
        """
        if not self._is_connected:
            logger.error("Bot is not connected")
            return

        self._protocol.send_irc_data(data, log)

    def run(self) -> None:
        """
        starts the clients mainloop
        :return: None
        """
        # create task of our run method
        self._loop.create_task(self._connect_and_run(), name="InitialConnectAndRun")
        # run the loop forever
        try:
            self._loop.run_forever()
        except KeyboardInterrupt as error:
            self._stop_tasks_and_loop(error)
        logger.info("Stopped")

    def _stop_tasks_and_loop(self, error: KeyboardInterrupt) -> None:
        """
        stop tasks and loop
        :param error: error
        :return: None
        """
        logger.debug(error)
        if self._transport:
            self._transport.close()
        pending_tasks = asyncio.all_tasks(self._loop)

        async def wrapper():
            for task in pending_tasks:
                logger.debug(f"Cancelling {task}")
                task.cancel()
            await asyncio.gather(*pending_tasks, return_exceptions=True)
            logger.debug(f"Cancelled {pending_tasks}")

        logger.debug(f"Current Task: {asyncio.current_task(self._loop)}")
        self._loop.run_until_complete(wrapper())
        self._loop.stop()

    async def _connect_and_run(self) -> None:
        """
        connect and run irc loop
        :return: None
        """
        if self._use_proxies:
            try:
                self._current_proxy: Proxy = next(self._proxy_cycle)
                proxy_type: ProxyType = self._current_proxy._proxy_type
                logger.debug(f"Using {proxy_type.name} Proxy {self._current_proxy}")
                sock = await self._current_proxy.connect(dest_host=self._server, dest_port=self._port)
            except ProxyError as error:
                logger.exception(error)
                await asyncio.sleep(self._retry_delay)
                await self._connect_and_run()
                return

            self._transport, self._protocol = await self._loop.create_connection(
                lambda: AsyncIRCClientProtocol(
                    on_connection_made=self._on_protocol_connection_made,
                    on_connection_lost=self._on_protocol_connection_lost,
                    on_data_received=self._on_protocol_data_received
                ), sock=sock
            )

        else:
            self._transport, self._protocol = await self._loop.create_connection(
                lambda: AsyncIRCClientProtocol(
                    on_connection_made=self._on_protocol_connection_made,
                    on_connection_lost=self._on_protocol_connection_lost,
                    on_data_received=self._on_protocol_data_received
                ), self._server, self._port
            )
        await self._on_protocol_done_connecting()

    async def _on_protocol_done_connecting(self) -> None:
        """
        called as soon as the protocol is done connecting and create_connection has returned
        :return: None
        """
        self.on_connected_to_server()

    def _on_protocol_connection_made(self, transport: transports.Transport) -> None:
        """
        on protocol connection made. DO NOT USE. USE _on_protocol_done_connecting instead.
        :param transport: transport
        :return: None
        """
        self._is_connected = True
        logger.debug(f"Connected to server with transport {transport}")

    def _on_protocol_connection_lost(self, exception: Exception) -> None:
        """
        on protocol connection lost
        :param exception: exception that caused the disconnect
        :return: None
        """
        self._is_connected = False
        if exception is Exception:
            logger.exception(f"Disconnected from server with exception: {exception}")
        else:
            logger.warning(f"Disconnected from server: {exception}")

        self._transport.close()
        self.on_disconnected_from_server(exception)

    def _on_protocol_data_received(self, message: str) -> None:
        """
        on protocol data received
        :param message: message
        :return: None
        """


class TwitchIRCBotInterfaceMixin:
    """
    holds interface methods for third-party-users to retain visibility in irc class
    """

    async def on_client_ready(self, message: Message) -> None:
        """called when client is ready (001:RPL_WELCOME)"""

    async def on_host_info(self, message: Message) -> None:
        """called when server sends host info (002:RPL_YOURHOST)"""

    async def on_host_creation_info(self, message: Message) -> None:
        """called when server sends creation info (003:RPL_CREATED)"""

    async def on_host_mode_info(self, message: Message) -> None:
        """called on server sends user channel mode info (004:RPL_MYINFO)"""

    async def on_user_list_start(self, message: Message) -> None:
        """called on server starts sending user list info (353:RPL_NAMEREPLY)"""

    async def on_user_list_end(self, message: Message) -> None:
        """called on server ends sending user list info (366:RPL_ENDOFNAMES )"""

    async def on_message_of_the_day(self, message: Message) -> None:
        """called on server sends message of the day (372:RPL_MOTD)"""

    async def on_message_of_the_day_start(self, message: Message) -> None:
        """called on server starts sending message of the day (375:RPL_MOTDSTART)"""

    async def on_message_of_the_day_end(self, message: Message) -> None:
        """called on server ends sending message of the day (376:RPL_ENDOFMOTD)"""

    async def on_no_nickname_given(self, message: Message) -> None:
        """called on no nickname given (431:ERR_NONICKNAMEGIVEN)"""

    async def on_nickname_in_use(self, message: Message) -> None:
        """called on nickname in use (433:ERR_NICKNAMEINUSE)"""

    async def on_banned_from_channel(self, message: Message) -> None:
        """called on client banned from channel (474:ERR_BANNEDFROMCHANNEL)"""

    async def on_client_joined(self, message: Message) -> None:
        """called when client joined (JOIN)"""

    async def on_user_join(self, message: Message) -> None:
        """called if any user joins the channel (JOIN)"""

    async def on_user_left(self, message: Message) -> None:
        """called on user leaves or gets banned (PART)"""

    async def on_irc_capabilities(self, message: Message) -> None:
        """called when receiving command and tag capabilities (CAP) """

    async def on_user_state(self, message: Message) -> None:
        """called on user state (USERSTATE)"""

    async def on_global_user_state(self, message: Message) -> None:
        """called on global user state update (GLOBALUSERSTATE)"""

    async def on_notice(self, message: Message) -> None:
        """called on notice (NOTICE)"""

    async def on_hosttarget(self, message: Message) -> None:
        """called on hosttarget (HOSTTARGET)"""

    async def on_roomstate(self, message: Message) -> None:
        """called on roomstate (ROOMSTATE)"""

    async def on_ping(self, message: Message) -> None:
        """called on ping received (PING)"""

    async def on_pong(self, message: Message) -> None:
        """called on pong received (PONG)"""

    async def on_reconnect(self, message: Message) -> None:
        """called on reconnect (RECONNECT)"""

    async def on_user_notice(self, message: Message) -> None:
        """called on user notice (USERNOTICE)"""

    async def on_clear_chat(self, message: Message) -> None:
        """called on clear chat (CLEARCHAT)"""

    async def on_message(self, message: Message) -> None:
        """called on message (PRIVMSG)"""

    async def on_raid(self, message: Message) -> None:
        """called on raid event (msg-id == raid)"""


class TwitchIRCBot(IRCClient, TwitchIRCBotInterfaceMixin):
    TWITCH_IRC_SERVER: str = "irc.chat.twitch.tv"
    TWITCH_IRC_PORT: int = 6667
    command_callbacks: dict[str, CommandCallback] = {}
    case_insensitive: list[str] = []
    tasks: list[Callable] = []
    _running_tasks: list[Callable] = []

    def __init__(self, oauth_token: str, nick_name: str, channel: str, timeout: int = 500, **kwargs):
        """
        constructor
        :param oauth_token: oauth token
        :param nick_name: nickname to use
        :param channel: channel name
        :param timeout: request ping after n seconds and reconnect after n seconds if no answer was received
        :param kwargs: kwargs
        """
        super().__init__(
            server=kwargs.pop("server", TwitchIRCBot.TWITCH_IRC_SERVER),
            port=kwargs.pop("port", TwitchIRCBot.TWITCH_IRC_PORT),
            **kwargs
        )

        self._oauth_token: str = oauth_token
        self._nick_name: str = nick_name
        self._channel: str = channel
        self._has_commands: bool = False
        self._has_tags: bool = False
        self._timeout: int = timeout
        self._disconnect_timer: Timer = Timer(self._timeout, self._on_disconnect_timer_timeout)
        self._pong_response_timer: Timer = Timer(20, self._on_pong_response_timer_timeout)

    @staticmethod
    def command(name: str, mod_only: bool = False, aliases: list[str] = None, case_sensitive: bool = True):
        """
        registers function in command table
        :param name: name to register as
        :param mod_only: is command mod only
        :param aliases: alternative names
        :param case_sensitive: case-sensitive commands
        :return: decorator
        """

        if aliases is None:
            aliases = []

        def decorator(function):
            """
            Decorator function to wrap the original function and add it to the command table.

            :param function: The function to be wrapped.
            :return: The wrapper function.
            """

            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                """
                Wrapper function that executes the original function.

                :param args: Positional arguments passed to the function.
                :param kwargs: Keyword arguments passed to the function.
                :return: The result of the original function.
                """
                return await function(*args, **kwargs)

            command_callback: CommandCallback = CommandCallback(name, wrapper, mod_only, aliases, case_sensitive)

            TwitchIRCBot.command_callbacks[name] = command_callback

            if not case_sensitive:
                TwitchIRCBot.case_insensitive.append(name.lower())

            for alias in aliases:
                TwitchIRCBot.command_callbacks[alias] = command_callback
                TwitchIRCBot.case_insensitive.append(alias.lower())

            return wrapper

        return decorator

    @staticmethod
    def loop(seconds: int = 0, time: str = None, wait_first: bool = False):
        """
        repeat function in given intervals
        :param seconds: seconds
        :param time: time to repeat function at (for example 12:00)
        :param wait_first: wait first before executing the function
        :return: None
        """

        def decorator(function: Callable):
            """
            decorator
            :param function: functon to decorate
            :return: wrapper
            """

            async def wrapper(*args, **kwargs):
                """
                wrapper function
                :param args: args
                :param kwargs: kwargs
                :return: None
                """
                if wait_first:
                    while True:
                        if time is None:
                            await asyncio.sleep(seconds)
                        else:
                            await asyncio.sleep(get_time_difference(time))
                        await function(*args, **kwargs)
                else:
                    while True:
                        await function(*args, **kwargs)

                        if time is None:
                            await asyncio.sleep(seconds)
                        else:
                            await asyncio.sleep(get_time_difference(time))

            TwitchIRCBot.tasks.append(wrapper)

            return wrapper

        return decorator

    def _send_pong(self) -> None:
        """
        send pong response
        :returns: None
        """
        self.send_irc_data("PONG :tmi.twitch.tv")

    def _send_ping(self) -> None:
        """
        send pong response
        :returns: None
        """
        self.send_irc_data("PING :tmi.twitch.tv")

    def _on_pong(self) -> None:
        """
        on pong received
        :return: None
        """
        self._pong_response_timer.cancel()

    def _reconnect(self) -> None:
        """
        reconnect to server
        :returns: None
        """
        self._pong_response_timer.cancel()
        self._disconnect_timer.cancel()

        def wrapper():
            self._transport.close()
            pending_tasks = asyncio.all_tasks(self._loop)
            for task in pending_tasks:
                logger.warning(f"Stopping task {task}")
                task.cancel()
            logger.info(asyncio.current_task(self._loop))
            asyncio.gather(*pending_tasks, return_exceptions=True)
            self._loop.create_task(self._connect_and_run())

        self._loop.call_soon_threadsafe(wrapper)

    def _check_commands(self, message: Message) -> None:
        """
        check if message contains a command
        """
        # is not a command
        if not message.parameters.startswith("!"):
            return

        # split after '!'
        command_parts: list[str] = message.parameters[1:].split()
        command_name: str = command_parts[0]

        if command_name.lower() in self.case_insensitive:
            command_name = command_name.lower()

        command_callback: CommandCallback = TwitchIRCBot.command_callbacks.get(command_name)

        if command_callback is None:
            logger.warning(f"No bound command found for: {command_parts}")
            return

        # is mod only
        if command_callback.mod_only and not self.is_mod_or_broadcaster(message):
            logger.debug(f"User {message.source.nick} tried to issue mod-only command: {message.parameters}")
            return

        self._loop.create_task(command_callback.callback(self, message))

    def _check_user_notice(self, message: Message) -> None:
        """
        check user notice for certain events
        :param message: message
        :return: None
        """
        if self._has_tags and message.tags.get("msg-id") == "raid":
            self._loop.create_task(self.on_raid(message))

    async def _on_disconnect_timer_timeout(self) -> None:
        """
        on disconnect timer times out
        :return: None
        """
        self._send_ping()
        self._pong_response_timer.start()

    async def _on_pong_response_timer_timeout(self) -> None:
        """
        on pong response timer times out
        :return: None
        """
        self._reconnect()

    async def _on_protocol_done_connecting(self) -> None:
        """
        Do not use on_connected_to_server: Should be reserved for users
        :return: None
        """
        logger.debug("Protocol done connecting")
        await super()._on_protocol_done_connecting()

        # start timer
        self._disconnect_timer.start()

        for task in self.tasks:
            self._loop.create_task(task(self))

        self._login()
        self._requests_tags()
        self._request_commands()
        self.join(self._channel)

    def _login(self) -> None:
        """
        login to twitch using oauth token and nickname
        :return: None
        """
        logger.debug("Attempting login")
        self.send_irc_data(f"PASS oauth:{self._oauth_token}")
        self.send_irc_data(f"NICK {self._nick_name}")

    def _requests_tags(self) -> None:
        """
        request tags
        :return: None
        """
        logger.debug("Request Tags capability.")
        self.send_irc_data("CAP REQ :twitch.tv/tags")

    def _request_commands(self) -> None:
        """
        request commands
        :return: None
        """
        logger.debug("Request commands capability.")
        self.send_irc_data("CAP REQ :twitch.tv/commands")

    def _on_protocol_data_received(self, message: str) -> None:
        """
        on protocol data received
        :param message: message as string
        :return: None
        """
        if not message:
            return logger.debug("Message is empty.")

        # restart timer
        self._disconnect_timer.restart()

        logger.debug(f"Parsing: {message}")
        parsed_message: Message = parse_message(message)

        if parsed_message is None:
            return logger.debug("Nothing parsed.")

        logger.debug(f"Parsed: {parsed_message}")

        callback: Union[Callable[[Message], Coroutine[Any, Any, None]], None]
        match parsed_message.command.command:
            case "CAP":
                if parsed_message.parameters == "twitch.tv/tags":
                    self._has_tags = True
                elif parsed_message.parameters == "twitch.tv/commands":
                    self._has_commands = True
                callback = self.on_irc_capabilities

            case "JOIN":
                callback = self.on_client_joined if parsed_message.source.nick == self._nick_name else self.on_user_join

            case "NOTICE":
                callback = self.on_notice

            case "CLEARCHAT":
                callback = self.on_clear_chat

            case "HOSTTARGET":
                callback = self.on_hosttarget

            case "PRIVMSG":
                self._check_commands(parsed_message)
                callback = self.on_message

            case "ROOMSTATE":
                callback = self.on_roomstate

            case "USERSTATE":
                callback = self.on_user_state

            case "GLOBALUSERSTATE":
                callback = self.on_global_user_state

            case "PING":
                self._send_pong()
                callback = self.on_ping

            case "PONG":
                self._on_pong()
                callback = self.on_pong

            case "RECONNECT":
                self._reconnect()
                callback = self.on_reconnect

            case "USERNOTICE":
                self._check_user_notice(parsed_message)
                callback = self.on_user_notice

            case "PART":
                callback = self.on_user_left

            case "001":  # successful connection + other auth details
                callback = self.on_client_ready

            case "002":  # server hostname and version
                callback = self.on_host_info

            case "003":  # server creation date
                callback = self.on_host_creation_info

            case "004":  # supported user/channel modes + other stuff
                callback = self.on_host_mode_info

            case "353":  # list users in channel
                callback = self.on_user_list_start

            case "366":  # end of user list (353)
                callback = self.on_user_list_end

            case "372":  # message of the day
                callback = self.on_message_of_the_day

            case "375":  # start message of the day list
                callback = self.on_message_of_the_day_start

            case "376":  # end of message of the day list
                callback = self.on_message_of_the_day_end

            case "431":  # invalid nick
                callback = self.on_no_nickname_given

            case "433":  # nick in use
                callback = self.on_nickname_in_use

            case "474":  # banned
                callback = self.on_banned_from_channel

            case _:
                return logger.warning(f"Invalid command: Callback not found for: {parsed_message.command.command}")

        if callback is None:
            return logger.error("Callback must not be None.")

        self._loop.create_task(callback(parsed_message))

    def join(self, channel: str) -> None:
        """
        join channel
        :param channel: name
        :return: None
        """
        logger.debug(f"Joining {channel}")
        self.send_irc_data(f"JOIN #{channel}")

    def leave(self, channel: str) -> None:
        """
        leave channel.
        :param channel: channel to leave
        :return: None
        """
        logger.debug(f"Leaving {channel}")
        self.send_irc_data(f"PART #{channel}")

    def send_chat_message(self, text: str, channel: str = None) -> None:
        """
        send chat message
        :param text: text to send
        :param channel: channel to send message in
        :return: None
        """
        channel = self._channel if channel is None else channel
        self.send_irc_data(f"PRIVMSG #{channel} :{text}")

    def is_mod(self, message: Message) -> bool:
        """
        checks if issuer is mod
        :param message: message
        :return: bool
        """
        if not self._has_tags:
            logger.warning("Client has no tags: Cannot check.")
            return False

        if message.tags is None or message.tags.get("badges") is None:
            return False

        return message.tags.get("mod") == "1"

    def is_broadcaster(self, message: Message) -> bool:
        """
        checks if issuer is broadcaster
        :param message: message
        :return: bool
        """
        if not self._has_tags:
            logger.warning("Client has no tags: Cannot check.")
            return False

        if message.tags is None or message.tags.get("badges") is None:
            return False

        return message.tags.get("badges", {}).get("broadcaster", "") == '1'

    def is_mod_or_broadcaster(self, message: Message) -> bool:
        """
        checks if msg is either mod or broadcaster
        :param message: message
        :return: bool
        """
        return self.is_mod(message) or self.is_broadcaster(message)
