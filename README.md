# EFB Telegram Master Channel (ETM)
<!-- badges -->

**Channel ID**: `ehforwarderbot.channels.master.blueset.telegram`

ETM is a Telegram Master Channel for EH Forwarder Bot, based 
on Telegram Bot API, `python-telegram-bot`.

## Alpha version
This is an unstable alpha version, and functionality may 
change at any time.

## Requirements
* Python >= 3.5
* EH Forwarder Bot >= 2.0.0
* ffmpeg
* libmagic

## Configuration
Configuration file is stored at 
`<profile storage diretory>/ehforwarderbot.channels.master.blueset.telegram/config.yaml`. 
The path of your profile storage directory depends on your configuration.

__(As of EFB 2.0.0a1: Default profile storage directory is located at `~/.ehforwarderbot/defualt`)__

A sample config file can be as follows:

```yaml
##################
# Required items #
##################
# You are required to fill the option below,
# or this channel will not work.

# Telegram bot token.
# This is the token you obtained from BotFather
token: "12345678:1a2b3c4d5e6g7h8i9j"

# List of Telegram User IDs of admins
# ETM will only process messages and commands from users
# listed below. This ID can be obtained from various ways 
# on Telegram.
admins:
- 102938475
- 91827364

##################
# Optional items #
##################
# The following options are optional. Lack of this section
# will only affect an additional part of functionality of
# this channel.

# API tokens required for speech recognition 
speech_api:
    # Microsoft (Bing) speech recognition token
    # API key can be obtained from
    # https://www.microsoft.com/cognitive-services/en-us/speech-api
    bing: ["token1", "token2"]
    # Baidu speech recognition token
    # API key can be obtained from
    # http://yuyin.baidu.com/
    baidu:
        app_id: 123456
        api_key: "API_KEY_GOES_HERE"
        secret: "SECRET_KEY_GOES_HERE"
        

# Experimental Flags
# This section can be used to enable experimental functionality.
# However, those features may be changed or removed at any time.
# Options for this section is explained afterward.
flags:
    option_one: 10
    option_two: false
    option_three: "foobar"
```


## Usage
At the beginning, messages from all senders will be sent to 
the user directly, that means every message  will be mixed in 
the same conversation. By linking a chat, you can redirect 
messages from a specific sender to an empty group for a more 
organized conversation.

In a nutshell, ETM offers the following commands, you can also 
send it to BotFather for the command list.

```
help - Show commands list.
link - Link a remote chat to a group.
unlink_all - Unlink all remote chats from a group.
info - Display information of the current Telegram chat.
chat - Generate a chat head.
recog - Recognize a speech by replying to it.
extra - Access extra functionalities.
```

**Note**    
In case of multiple admins are assigned, they may all 
send message on your behalf, but only the 0th admin can 
receive direct message from the bot.

### `/link`: Link a chat
1. Create a new group, invite your bot to the group
2. Send `/link` directly to the bot, then select your preferred slave chat.
3. Tap "Link" and select your new group.  
   _You can also choose to unlink or relink a linked chat from this menu._
4. Tap "Start" at the bottom of your screen, and you should see a success 
   message: "Chat associated."

**Note**  
You may introduce other non-ETM admins to the group, however, they:

    * Can read all messages send from the related remote chat;
    * May NOT send message on your behalf.

Also, you can send `/unlink_all` to a group to unlink all remote chats from it.

### Send a message
#### Send to a linked chat
You can send message as you do in a normal Telegram chat.

What is supported:

* Send/forward message in all supported types
* Direct reply to a message
* Send message with inline bot in supported types

What is NOT supported:

* @ reference
* Markdown/HTML formatting
* Messages with unsupported types

#### Send to a non-linked chat
To send a message to a non-linked chat, you should "direct reply" 
to a message or a "chat head" that is sent from your recipient. 
Those messages should appear only in the bot conversation.

In a non-linked chat, direct reply will not be delivered to the 
remote channel, everything else is supported as it does in a 
linked chat.

#### `/chat`: Chat head
If you want to send a message to a non-linked chat which has 
not yet sent you a message, you can ask ETM to generate a 
"chat head". Chat head works similarly to an incoming message, 
you can reply to it to send messages to your recipient.

Send `/chat` to the bot, and choose a chat from the list. 
When you see "Reply to this message to send to <chat name> 
from <channel>", it's ready to go.

##### Advanced feature: Filtering
If you have just too much chats, and being too tired for 
keep tapping `Next >`, or maybe you just want to find a 
way to filter out what you're looking for, now ETM has 
equipped `/chat` and `/list` with filtering feature. 
Attach your keyword behind, and you can get a filtered result.

E.g.: `/chat Eana` will give you all chats has the word "Eana".

**Technical Details**  
The filter query is in fact a regular expression matching. 
We used Python's `re.search` with flags `re.DOTALL | re.IGNORECASE` 
in this case, i.e.: `.` matches everything including line breaks, 
and the query is NOT case-sensitive. Each comparison is done 
against a specially crafted string which allows you to filter 
multiple criteria.

**TODO**: Update this string format 

```
Channel: Dummy Channel
Name: John Doe
Alias: Jonny
ID: john_doe
Type: User
Status: Linked
```

> _Type can be either "User" or "Group"_  
> _Status can be empty or either "Linked" or "Muted"_

Examples:

* Look for all WeChat groups: `Channel: WeChat.*Type: Group`
* Look for everyone who has an alias `Name: (.*?)\nAlias: (?!\1)`
* Look for all entries contain "John" and "Jonny" in any order: `(?=.*John)(?=.*Jonny)"`

### `/extra`: External commands from slave channels ("extra functions")
Some slave channels may provide commands that allows you to 
remotely control those accounts, and achieve extra functionality, 
those commands are called "extra functions". To view the list of 
available extra functions, send `/extra` to the bot, you will 
receive a list of commands available, together with their usages.

Those commands are named like "`/<number>_<command_name>`", 
and can be called like a Linux/unix CLI utility. (of course, 
please don't expect piping etc to be supported)

### `/recog`: Speech recognition
If you have entered a speech recognition service API keys, you 
can use it to convert speech in voice messages into text.

Reply any voice messages in a conversation with the bot, 
with the command `/recog`, and the bot will try to convert 
it to text using those speech recognition services enabled.

If you know the language used in this message, you can also 
attach the language code to the command for a more precise 
conversion.

Supported language codes:

Code | Baidu | Bing
---|---|---
en, en-US | English | English (US)
en-GB | - | English (UK)
en-IN | - | English (India)
en-NZ | - | English (New Zealand)
en-AU | - | English (Australia)
en-CA | - | English (Canada)
zh, zh-CN | Mandarin | Mandarin (China Mainland)
zh-TW | - | Mandarin (Taiwan)
zh-HK | - | Mandarin (Hong Kong)
ct | Cantonese | -
de-DE | - | German
ru-RU | - | Russian
ja-JP | - | Japanese
ar-EG | - | Arabic
da-DK | - | Danish
es-ES | - | Spanish (Spain)
es-MX | - | Spanish (Mexico)
fi-FI | - | Finnish
nl-NL | - | Dutch
pt-BR | - | Portuguese (Brazil)
pt-PT | - | Portuguese (Portugal)
ca-ES | - | Catalan
fr-FR | - | French (France)
fr-CA | - | French (Canada)
ko-KR | - | Korean
nb-NO | - | Norwegian
it-IT | - | Italian
sv-SE | - | Swedish


## Experimental flags
The following flags are experimental features, may change, 
break, or disappear at any time. Use at your own risk.

Flags can be enabled in the `flags` key of the configuration 
file, e.g.:

```yaml
flags:
    flag_name: flag_value
```

* `no_conversion` _(bool)_  [Default: `False`]
  Disable audio conversion, send all audio file as is, and 
  let Telegram to handle it.  
  _Only works in linked chats._
* `chats_per_page` _(int)_ [Default: `10`]  
  Number of chats shown in when choosing for `/chat` and `/link` 
  command. An overly large value may lead to malfunction of 
  such commands.
* `network_error_prompt_interval` _(int)_ [Default: `100`]  
  Notify the user about network error every `n` errors 
  received. Set to 0 to disable it.
* `text_as_html` _(bool)_ [Default: `False`]  
  Parse all text messages as Telegram HTML. Tags 
  supported: `a`, `b`, `strong`, `i`, `em`, `code`, `pre`.
* `multiple_slave_chats` _(bool)_  [Default: `True`]  
  Link more than one remote chat to one Telegram group. 
  Send and reply as you do with an unlinked chat. 
  Disable to link remote chats and Telegram 
  group one-to-one.
* `prevent_message_removal` _(bool)_ [Default: `True`]  
  When a slave channel requires to remove a message, EFB will
  ignore the request if this value is `True`.