# AsyncIRCClient
Async (Twitch-) IRC client

First async code so takee everything with a bit of caution

# Installation
`pip install AsyncIRCClient`

Example usage

```py
from loguru import logger

from async_irc_client.async_irc_client import TwitchIRCBot, Message


class MyBot(TwitchIRCBot):

    # subscribe to twitch's irc events
    async def on_client_ready(self, message: Message) -> None:
        logger.info("Bot is Ready")

    # create commands
    @TwitchIRCBot.command("test")
    async def test_command(self, message: Message) -> None:
        self.send_chat_message(f"Hello World {message.source.nick}")

    # mod only command
    @TwitchIRCBot.command("mod_test", mod_only=True)
    async def mod_test_command(self, message: Message) -> None:
        self.send_chat_message(f"Hello World mod {message.source.nick}")

    @TwitchIRCBot.command("alias_test", aliases=["alias_1", "alias_2"])
    async def alias_test_command(self, message: Message) -> None:
        self.send_chat_message("Call as alias!")

    # when using case-insensitive commands you may not use
    # any other command with the same name as any case-insensitive combination
    # works with aliases
    @TwitchIRCBot.command("case_insensitive", case_sensitive=False)
    async def case_insensitive_command(self, message: Message) -> None:
        self.send_chat_message("Case insensitive")

    # repeat a task
    # runs once the client is ready and after the specified time interval
    # here 1000s
    @TwitchIRCBot.loop(1000)
    async def my_task(self):
        logger.info("Hello World")

    # repeat a task at given time
    # is 1 second delayed to prevent double trigger inaccuracies
    @TwitchIRCBot.loop(time="08:36")
    async def my_timed_task(self):
        logger.info("Hello World at 08:36")


if __name__ == "__main__":
    from async_irc_client import Proxy, ProxyType

    MyBot(
        oauth_token="YOURTOKEN",
        nick_name="BOTNAME",
        channel="CHANNELNAME",
        proxies=[
            Proxy(ProxyType.HTTP, "ip", 1234),
            Proxy(ProxyType.HTTP, "ip", 1234, password="password", username="username"),
            Proxy.from_url("proxy_url")
        ]
    ).run()

```
