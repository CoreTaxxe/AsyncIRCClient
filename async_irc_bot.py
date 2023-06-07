import asyncio
from asyncio import transports
from dataclasses import dataclass
from typing import Union, Callable, Any, Coroutine

from loguru import logger


def is_event_loop_running() -> bool:
    """
    check if asyncio has loop running
    :return: bool
    """
    try:
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        return loop.is_running()
    except RuntimeError as _error:
        return False


@dataclass
class Command(object):
    command: Union[None, str] = None
    channel: Union[None, str] = None
    channel_raw: Union[None, str] = None
    bot_command: Union[None, str] = None
    bot_command_params: Union[None, str] = None
    is_cap_request_enabled: [None, bool] = None


@dataclass
class Source(object):
    nick: Union[None, str] = None
    host: Union[None, str] = None


@dataclass
class Message(object):
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
            logger.warning(f"Unsupported IRC command: {command_parts[2]}")
            return None

        case "001":
            parsed_command.command = command_parts[0]
            parsed_command.command = command_parts[1]

        case "002" | "003" | "004" | "353" | "366" | "372" | "375" | "376":
            logger.debug(f"Numeric message: {command_parts[0]}")

        case _:
            logger.error(f"\n\nUnexpected Command: {command_parts[0]} ({command_parts})\n")
            return None

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
    logger.debug(f"Parsing: {message_string}")

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
        self._transport = transport
        if self._on_connection_made_callback is not None:
            self._on_connection_made_callback(transport)

    def connection_lost(self, exception: Union[Exception, None]) -> None:
        """
        connecting to server has been lost
        :param exception: exception
        :return: None
        """
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


class IRCClientInterfaceMixin(object):
    async def on_connected_to_server(self) -> None:
        """
        called as soon as the client connected to the server
        :return: None
        """

    async def on_disconnected_from_server(self, exception: Exception) -> None:
        """
        called as soon as the client disconnects from the server
        :param exception: exception that caused the disconnect
        :return: None
        """


class IRCClient(IRCClientInterfaceMixin):

    def __init__(self, server: str, port: int, loop: Union[asyncio.AbstractEventLoop, None] = None):
        """
        constructor
        :param server: server to connect to
        :param port: port to connect to
        :param loop: set custom event loop
        """
        self._server: str = server
        self._port: int = port
        self._loop: Union[asyncio.AbstractEventLoop, None] = loop
        self._protocol: Union[AsyncIRCClientProtocol, None] = None
        self._transport: Union[transports.Transport, None] = None
        self._event_handler: dict[str, Callable] = {}
        self._is_connected: bool = False

    def send_irc_data(self, data: str) -> None:
        """
        send irc data
        :param data: data to send
        :return: None
        """
        if not self._is_connected:
            return logger.error("Bot is not connected")

        self._protocol.send_irc_data(data)

    def run(self) -> None:
        """
        starts the clients mainloop
        :return: None
        """
        # get event loop if none set
        if self._loop is None:
            self._loop = asyncio.get_event_loop() if is_event_loop_running() else asyncio.new_event_loop()

        # create task of our run method
        self._loop.create_task(self._connect_and_run())
        # run the loop forever
        self._loop.run_forever()

    async def _connect_and_run(self) -> None:
        """
        connect and run irc loop
        :return: None
        """
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
        await self.on_connected_to_server()

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
        logger.exception(f"Disconnected from server with exception: {exception}")
        self._transport.close()
        self.on_disconnected_from_server(exception)

    def _on_protocol_data_received(self, message: str) -> None:
        """
        on protocol data received
        :param message: message
        :return: None
        """


class TwitchIRCBotInterfaceMixin(object):
    """
    holds interface methods for third-party-users to retain visibility in irc class
    """

    async def on_irc_capabilities(self, message: Message) -> None:
        """called when receiving command and tag capabilities"""

    async def on_client_ready(self, message: Message) -> None:
        """called when client is ready"""

    async def on_client_joined(self, message: Message) -> None:
        """called when client joined"""

    async def on_user_join(self, message: Message) -> None:
        """called if any user joins the channel"""

    async def on_user_left(self, message: Message) -> None:
        """called if any user leaves or gets banned"""

    async def on_global_user_state(self, message: Message) -> None:
        """called on global user state update"""


class TwitchIRCBot(IRCClient, TwitchIRCBotInterfaceMixin):
    TWITCH_IRC_SERVER: str = "irc.chat.twitch.tv"
    TWITCH_IRC_PORT: int = 6667
    command_callbacks: dict[str, Callable] = {}

    def __init__(self, oauth_token: str, nick_name: str, channel: str, **kwargs):
        super().__init__(
            server=kwargs.pop("server", TwitchIRCBot.TWITCH_IRC_SERVER),
            port=kwargs.pop("port", TwitchIRCBot.TWITCH_IRC_PORT),
            **kwargs
        )

        self._oauth_token: str = oauth_token
        self._nick_name: str = nick_name
        self._channel: str = channel

    @staticmethod
    def command(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """
        registers function in command table
        :param name: name to register as
        :return: decorator
        """

        def decorator(function: Callable[..., Any]) -> Callable[..., Any]:
            """
            decorator function
            :param function: decorated function
            :return: wrapper
            """

            def wrapper(*args: Any, **kwargs: Any) -> Any:
                """
                wrapper
                :param args: args
                :param kwargs: kwargs
                :return: function returns values
                """
                return function(*args, **kwargs)

            # Add the wrapped function to the command callbacks dictionary
            TwitchIRCBot.command_callbacks[name] = function

            return wrapper

        return decorator

    async def _on_protocol_done_connecting(self) -> None:
        """
        Do not use on_connected_to_server: Should be reserved for users
        :return: None
        """
        await super()._on_protocol_done_connecting()
        await self._login()
        await self._requests_tags()
        await self._request_commands()
        await self.join(self._channel)

    async def _login(self) -> None:
        """
        login to twitch using oauth token and nickname
        :return: None
        """
        logger.debug("Attempting login")
        self.send_irc_data(f"PASS oauth:{self._oauth_token}")
        self.send_irc_data(f"NICK {self._nick_name}")

    async def _requests_tags(self) -> None:
        """
        request tags
        :return: None
        """
        logger.debug("Request Tags capability.")
        self.send_irc_data("CAP REQ :twitch.tv/tags")

    async def _request_commands(self) -> None:
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

        parsed_message: Message = parse_message(message)

        logger.debug(f"Parsed: {parsed_message}")

        callback: Union[Callable[[Message], Coroutine[Any, Any, None]], None]
        match parsed_message.command.command:
            case self._nick_name:
                callback = self.on_client_ready

            case "CAP":
                callback = self.on_irc_capabilities

            case "JOIN":
                callback = self.on_client_joined if parsed_message.source.nick == self._nick_name else self.on_user_join

            case _:
                return logger.warning(f"Invalid command: Callback not found for: {parsed_message.command.command}")

        if callback is None:
            return logger.error("Callback must not be None.")

        self._loop.create_task(callback(parsed_message))

    async def join(self, channel: str) -> None:
        """
        join channel
        :param channel: name
        :return: None
        """
        logger.debug(f"Joining {channel}")
        self.send_irc_data(f"JOIN #{channel}")

