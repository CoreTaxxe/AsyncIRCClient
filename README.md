# AsyncIRCClient
Async (Twitch-) IRC client

First async code so takee everything with a bit of caution

Example usage

```py
from async_irc_bot.async_irc_client import TwitchIRCBot, Message
from loguru import logger


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

    # repeat a task
    # runs once the client is ready and after the specified time interval
    # here 1000s
    @TwitchIRCBot.loop(1000)
    async def my_task(self):
        logger.info("Hello World")


if __name__ == "__main__":
    MyBot(oauth_token="YOURTOKEN", nick_name="BOTNAME", channel="CHANNELNAME").run()


```