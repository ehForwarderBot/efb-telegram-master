import shutil
from getpass import getpass
from gettext import translation
from typing import Optional

from PIL import Image, WebPImagePlugin
from bullet import YesNo, Numbers, Bullet
from pkg_resources import resource_filename

import cjkwrap
from ruamel.yaml import YAML
from telegram import Bot, TelegramError
from telegram.ext.filters import Filters
from telegram.ext import MessageHandler, Updater
from telegram.utils.request import Request

from ehforwarderbot import coordinator, utils
from ehforwarderbot.types import ModuleID

from . import TelegramChannel


def print_wrapped(text):
    paras = text.split("\n")
    for i in paras:
        print(*cjkwrap.wrap(i), sep="\n")


translator = translation("efb_telegram_master",
                         resource_filename('efb_telegram_master', 'locale'),
                         fallback=True)

_ = translator.gettext
ngettext = translator.ngettext


class DataModel:
    data: dict
    request: Optional[Request] = None
    building_default = False

    def __init__(self, profile: str, instance_id: str):
        print("==== etm_wizard, data mod, init", profile)
        coordinator.profile = profile
        self.profile = profile
        self.instance_id = instance_id
        self.channel_id = TelegramChannel.channel_id

        if instance_id:
            self.channel_id = ModuleID(self.channel_id + "#" + instance_id)
        self.config_path = utils.get_config_path(self.channel_id)
        self.yaml = YAML()
        if not self.config_path.exists():
            self.build_default_config()
        else:
            self.data = self.yaml.load(self.config_path.open())

    def build_default_config(self):
        self.data = {
            "token": "",
            "admins": [],
            "flags": {}
        }

        self.building_default = True

    def save(self):
        if self.building_default:
            with self.config_path.open('w') as f:
                f.write(_(
                    # TRANSLATORS: This part of text must be formatted in a monospaced font and no line shall exceed the width of a 70-cell-wide terminal.
                    "# ======================================\n"
                    "# EFB Telegram Master Configuration file\n"
                    "# ======================================\n"
                    "#\n"
                    "# This file configures how EFB Telegram Master Channel (ETM) works, and\n"
                    "# Who it belongs to.\n"
                    "#\n"
                    "# Required items\n"
                    "# --------------\n"
                    "#\n"
                    "# [Bot Token]\n"
                    "# The bot token obtained from @BotFather, in the format of numbers-colon-\n"
                    "# alphanumerals.\n"
                ))
                f.write("\n")
                self.yaml.dump({"token": self.data['token']}, f)
                f.write("\n")
                f.write(_(
                    # TRANSLATORS: This part of text must be formatted in a monospaced font.and no line shall exceed the width of a 70-cell-wide terminal.
                    "# [List of Admin User IDs]\n"
                    "# ETM will only process messages and commands from users\n"
                    "# listed below.  This ID can be obtained from various ways \n"
                    "# on Telegram.\n"
                ))
                f.write("\n")
                self.yaml.dump({"admins": self.data['admins']}, f)
                f.write("\n")
                f.write(_(
                    # TRANSLATORS: This part of text mst be formatted in a monospaced font.and no line shall exceed the width of a 70-cell-wide terminal.
                    "# Optional items\n"
                    "# --------------\n"
                    "#\n"
                    "# [Experimental Flags]\n"
                    "# This section can be used to toggle experimental functionality.\n"
                    "# These features may be changed or removed at any time.\n"
                    "# Refer to the project documentation for details.\n"
                    "#\n"
                    "# https://etm.1a23.studio\n"
                ))
                f.write("\n")
                self.yaml.dump({"flags": self.data['flags']}, f)
                f.write("\n")

                f.write(_(
                    # TRANSLATORS: This part of text mst be formatted in a monospaced font.and no line shall exceed the width of a 70-cell-wide terminal.
                    "# [Network configurations]\n"
                    "# Timeout tweaks, Proxy, etc.\n"
                    "# Refer to the project documentation for details.\n"
                    "#\n"
                    "# https://etm.1a23.studio\n"
                ))
                f.write("\n")
                if self.data.get('request_kwargs'):
                    self.yaml.dump(
                        {"request_kwargs": self.data['request_kwargs']}, f)
                else:
                    f.write(
                        "# request_kwargs:\n"
                        "#     # HTTP Proxy\n"
                        "#     proxy_url: http://127.0.0.1:80/\n"
                        "#     # username: admin\n"
                        "#     # password: password\n"
                        "#\n"
                        "#     # SOCKS5 proxy (Additional installations required)\n"
                        "#     # proxy_url: socks5://127.0.0.1:1080/\n"
                        "#     # urllib3_proxy_kwargs:\n"
                        "#     #     username: admin\n"
                        "#     #     password: password\n"
                    )
                f.write("\n")

                f.write(_(
                    # TRANSLATORS: This part of text mst be formatted in a monospaced font.and no line shall exceed the width of a 70-cell-wide terminal.
                    "# [RPC interface]\n"
                    "# Enable RPC interface of ETM where you can use scripts to manage data stored\n"
                    "# in the ETM message database or make queries.\n"
                    "# Refer to the project documentation for details.\n"
                    "#\n"
                    "# https://etm.1a23.studio\n"
                ))
                f.write("\n")
                if self.data.get('rpc'):
                    self.yaml.dump({"rpc": self.data['rpc']}, f)
                else:
                    f.write(
                        "# rpc:\n"
                        "#     server: 127.0.0.1\n"
                        "#     port: 8000\n"
                    )
                f.write("\n")
            with self.config_path.open() as f:
                self.data = self.yaml.load(f)
            self.building_default = False
        else:
            with self.config_path.open('w') as f:
                self.yaml.dump(self.data, f)


def input_bot_token(data: DataModel, default=None):
    prompt = _("Your Telegram Bot token: ")
    if default:
        prompt += f"[{default}] "
    while True:
        ans = input(prompt)
        if not ans:
            if default:
                return default
            else:
                print(_("Bot token is required. Please try again."))
                continue
        else:
            try:
                Bot(ans, request=data.request).get_me()
            except TelegramError as e:
                print_wrapped(str(e))
                print()
                print(_("Please try again."))
                continue
            return ans


def setup_proxy(data):
    if YesNo(prompt=_("Do you want to run ETM behind a proxy? "),
             prompt_prefix="[yN] ", default="n").launch():
        if data.data.get('request_kwargs') is None:
            data.data['request_kwargs'] = {}
        proxy_type = Bullet(prompt=_("Select proxy type"),
                            choices=['http', 'socks5']).launch()
        host = input(_("Proxy host (domain/IP): "))
        port = input(_("Proxy port: "))
        username = None
        password = None
        if YesNo(prompt=_("Does it require authentication? "),
                 prompt_prefix="[yN] ", default="n").launch():
            username = input(_("Username: "))
            password = getpass(_("Password: "))
        if proxy_type == 'http':
            data.data['request_kwargs']['proxy_url'] = f"http://{host}:{port}/"
            if username is not None and password is not None:
                data.data['request_kwargs']['username'] = username
                data.data['request_kwargs']['password'] = password
        elif proxy_type == 'socks5':
            try:
                import socks
            except ModuleNotFoundError as e:
                print_wrapped(_("You have not installed required extra package "
                                "to use SOCKS5 proxy, please install with the "
                                "following command:"))
                print()
                print("pip install 'python-telegram-bot[socks]'")
                print()
                raise e
            protocol = input(_("Protocol [socks5]: ")) or "socks5"
            data.data['request_kwargs']['proxy_url'] = f"{protocol}://{host}:{port}"
            if username is not None and password is not None:
                data.data['request_kwargs']['urllib3_proxy_kwargs'] = {
                    "username": username,
                    "password": password
                }
        data.request = Request(**data.data['request_kwargs'])


def setup_telegram_bot(data):
    print_wrapped(_(
        "1. Set up your Telegram Bot\n"
        "---------------------------\n"
        "ETM requires you to have a Telegram bot ready with you to start with."
    ))
    print()
    if data.data['token']:
        # Config has token ready.
        # Assuming user doesn't need help creating one
        data.data['token'] = input_bot_token(data, data.data['token'])
    else:
        # No config is ready.
        # prompt to guide user to create one.

        prompt_yes = _("Yes, please tell me how to make one.")
        prompt_no = _("No, I have already made one according to the docs.")

        choices = Bullet(prompt=_("Do you need help creating a bot?"),
                         choices=[prompt_no, prompt_yes])
        answer = choices.launch()

        if answer == prompt_yes:
            print_wrapped(_(
                "Follow this guide to create your first ETM Telegram Bot.\n"
                "\n"
                ">>> Step 1: Search @BotFather on Telegram, or follow the "
                "link below. You should be able to see a bot named "
                "“BotFather”."
            ))
            print("    https://t.me/BotFather")
            print()
            input(_("Press ENTER/RETURN to continue..."))
            print()
            print_wrapped(_(
                ">>> Step 2: Send /newbot to BotFather to create a new bot. "
                "Follow its prompts to give it a name and a username. "
                "Note that its username must end with “bot”.\n"
                "\n"
                "After setting its username, you should receive a long line "
                "of code called “token”. Keep it with you securely, we will "
                "need that later on."
            ))
            print()
            input(_("Press ENTER/RETURN to continue..."))
            print()
            print_wrapped(_(
                ">>> Step 3: Get the bot ready for ETM.\n"
                "Send /setjoingroups to BotFather, choose the bot you "
                "just created, then choose “Enable”. This will allow your bot "
                "to join groups.\n"
                "\n"
                "Send /setprivacy to BotFather, choose the bot you just "
                "created, then choose “Disable”. This will allow your bot to "
                "process all messages in groups it joined, not just commands."
            ))
            print()
            input(_("Press ENTER/RETURN to continue..."))
        print()
        data.data['token'] = input_bot_token(data)


def setup_telegram_bot_commands_list(data):
    prompt_yes = _("Yes, please update.")
    prompt_no = _("No, I want to keep the old commands list.")

    choices = Bullet(prompt=_("Do you want to update the list of commands of your bot?"),
                     choices=[prompt_yes, prompt_no])
    answer = choices.launch()

    if answer == prompt_yes:
        print(_("Updating commands list..."), end="", flush=True)
        Bot(data.data['token'], request=data.request).set_my_commands(
            [
                ("help", _("Show commands list.")),
                ("link", _("Link a remote chat to a group.")),
                ("unlink_all", _("Unlink all remote chats from a group.")),
                ("info", _("Display information of the current Telegram chat.")),
                ("chat", _("Generate a chat head.")),
                ("extra", _("Access additional features from Slave Channels.")),
                ("update_info", _("Update info of linked Telegram group.")),
                ("react", _("Send a reaction to a message, or show a list of reactors.")),
                ("rm", _("Remove a message from its remote chat.")),
            ]
        )

        print(_("OK"))
        print()
        input(_("Press ENTER/RETURN to continue..."))


def input_admin_ids(default=None):
    prompt = _("List of Admin User IDs, separated with comma: ")
    if default:
        default_prompt = ",".join(map(str, default))
        prompt += f"[{default_prompt}] "
    while True:
        ans = input(prompt)
        if not ans:
            if default:
                return default
            else:
                print(_("Admin IDs are required. Please try again."))
                continue
        else:
            try:
                values = [int(i.strip()) for i in ans.split(",")]
            except ValueError:
                print_wrapped(_("{input} is not a valid input. "
                                "Please try again.").format(input=ans))
                continue
            return values


def setup_admins(data):
    print()
    print_wrapped(_(
        "2. Set up Bot administrators\n"
        "----------------------------\n"
        "To protect your data privacy and security, you need to provide "
        "a list of users who can interact with this Telegram Bot."
    ))
    print()
    if data.data['admins']:
        data.data['admins'] = input_admin_ids(default=data.data['admins'])
    else:
        prompt_yes = _("Yes, I want to know how to get my ID.")
        prompt_no = _("No, I already know my ID.")

        choices = Bullet(prompt=_("Do you need help getting your ID?"),
                         choices=[prompt_no, prompt_yes])
        answer = choices.launch()

        if answer == prompt_yes:
            print(_("Starting ID bot..."), end="", flush=True)

            updater = Updater(token=data.data['token'],
                              request_kwargs=data.data.get(
                                  'request_kwargs', None),
                              use_context=True)
            updater.dispatcher.add_handler(
                MessageHandler(
                    Filters.all,
                    lambda update, context:
                    update.effective_message.reply_text(
                        _("Your Telegram user ID is {id}.").format(
                            id=update.effective_user.id
                        )
                    )
                )
            )
            updater.start_polling()

            print(_("OK"))
            print()

            print_wrapped(_(
                "Now, send any message to the bot you just created. You should "
                "be able to get a numerical ID. That is your Telegram user ID. "
                "Enter that below to set yourself as an admin."
            ))
            print()
            data.data['admins'] = input_admin_ids(default=data.data['admins'])
            print()
            print(_("Stopping ID bot..."), end="", flush=True)
            updater.stop()
            print(_("OK"))
        else:
            data.data['admins'] = input_admin_ids(default=data.data['admins'])


flags_settings = {
    "chats_per_page":
        (10, 'int', None,
         _('Number of chats shown in when choosing for /chat '
           'and /link command. An overly large value may lead '
           'to malfunction of such commands.')
         ),
    "multiple_slave_chats":
        (True, 'bool', None,
         _('Link more than one remote chat to one Telegram group. Send and '
           'reply as you do with an unlinked chat. Disable to link remote '
           'chats and Telegram group one-to-one.')
         ),
    "network_error_prompt_interval":
        (100, 'int', None,
         _('Notify the user about network error every '
           'n errors received. Set to 0 to disable it.')
         ),
    "prevent_message_removal":
        (True, 'bool', None,
         _('When a slave channel requires to remove a message, EFB will '
           'ignore the request if this value is true.')
         ),
    "auto_locale":
        (True, 'bool', None,
         _('Detect the locale from admins’ messages automatically. Locale '
           'defined in environment variables will be used otherwise.')
         ),
    "retry_on_error":
        (False, 'bool', None,
         _('Retry infinitely when an error occurred while sending request to '
           'Telegram Bot API. Note that this may lead to repetitive message '
           'delivery, as the respond of Telegram Bot API is not reliable, and '
           'may not reflect the actual result.')
         ),
    "send_image_as_file":
        (False, 'bool', None,
         _('Send all image messages as files, in order to prevent Telegram’s '
           'image compression in an aggressive way.')
         ),
    "message_muted_on_slave":
        ('normal', 'choices', ['normal', 'silent', 'mute'],
         _('Behavior when a message received is muted on slave channel '
           'platform.\n'
           '\n'
           '- normal: send to Telegram as normal message\n'
           '- silent: send to Telegram as normal message, but without '
           'notification sound\n'
           '- mute: do not send to Telegram')),
    "your_message_on_slave":
        ('silent', 'choices', ['normal', 'silent', 'mute'],
         _('Behavior when a message received is from you on slave channel '
           'platform. This overrides settings from message_muted_on_slave.\n'
           '\n'
           '- normal: send to Telegram as normal message\n'
           '- silent: send to Telegram as normal message, but without '
           'notification sound\n'
           '- mute: do not send to Telegram')),
    "animated_stickers":
        (False, 'bool', None,
         _('Enable experimental support to animated stickers. Note: you might '
           'need to install binary dependency "libcairo" to enable this '
           'feature.')
         ),
    "send_to_last_chat":
        ("warn", 'choices', ["enabled", "warn", "disabled"],
         _('Enable quick reply in non-linked chats.\n'
           '\n'
           '- enabled: Enable this feature without warning.\n'
           '- warn: Enable this feature and issue warnings every time when you '
           'switch a recipient with quick reply.\n'
           '- disabled: Disable this feature.')
         ),
    "default_media_prompt":
        ("emoji", 'choices', ["emoji", "text", "disabled"],
         _('Placeholder text when the a picture/video/file message has no caption.\n'
           '\n'
           '- emoji: Use emoji like 🖼️, 🎥, and 📄.\n'
           '- text: Use text like “Sent a picture/video/file”.\n'
           '- disabled: Use empty placeholders.')
         )
}


def setup_experimental_flags(data):
    print()
    widget = YesNo(prompt=_("Do you want to config experimental features? "),
                   prompt_prefix="[yN] ", default="n")
    if not widget.launch():
        return

    for key, value in flags_settings.items():
        default, cat, params, desc = value
        if data.data['flags'].get(key) is not None:
            default = data.data['flags'].get(key)
        if cat == 'bool':
            prompt_prefix = '[Yn] ' if default else '[yN] '
            print()
            print(key)
            print_wrapped(desc)

            ans = YesNo(prompt=f"{key}? ",
                        default='y' if default else 'n',
                        prompt_prefix=prompt_prefix) \
                .launch()

            data.data['flags'][key] = ans
        elif cat == 'int':
            print()
            print(key)
            print_wrapped(desc)
            ans = Numbers(prompt=f"{key} [{default}]? ", type=int) \
                .launch(default=default)
            data.data['flags'][key] = ans
        elif cat == 'choices':
            try:
                assert isinstance(params, list)
                default = params.index(default)
            except ValueError:
                default = 0
            print()
            print(key)
            print_wrapped(desc)
            ans = Bullet(prompt=f"{key}?", choices=params) \
                .launch(default=default)
            data.data['flags'][key] = ans


def setup_network_configurations(data):
    print()
    proceed = YesNo(prompt=_("Do you want to adjust network configurations? "
                             "(connection timeout) "),
                    default="n",
                    prompt_prefix="[yN] ").launch()
    if not proceed:
        return

    print_wrapped(_(
        "For meanings and significances of the following values, please "
        "consult the module documentations."
    ))
    print()
    print("https://etm.1a23.studio/")
    print()

    if YesNo(prompt=_("Do you want to change timeout settings? "),
             prompt_prefix="[yN] ", default="n").launch():
        if data.data.get('request_kwargs') is None:
            data.data['request_kwargs'] = {}
        data.data['request_kwargs']['read_timeout'] = \
            Numbers(prompt=_("read_timeout (in seconds): ")).launch()
        data.data['request_kwargs']['connect_timeout'] = \
            Numbers(prompt=_("connect_timeout (in seconds): ")).launch()


def setup_rpc(data):
    print()
    print_wrapped(_(
        "To learn about what RPC is and what it does, please "
        "visit the module documentations."
    ))
    print()
    print("https://etm.1a23.studio/")
    print()

    proceed = YesNo(prompt=_("Do you want to enable RPC interface? "),
                    prompt_prefix="[yN] ", default="n").launch()
    if not proceed:
        return

    server = "127.0.0.1"
    port = 8000

    if 'rpc' in data.data:
        server = data.data['rpc']['server']
        port = data.data['rpc']['port']

    server = input(_("RPC server: ") + f"[{server}] ") or server
    port = int(input(_("Proxy port: ") + f"[{port}] ") or port)

    data.data['rpc'] = {
        "server": server,
        "port": port
    }


def prerequisites_check():
    print(_("Checking ffmpeg installation..."), end="", flush=True)
    if shutil.which('ffmpeg') is None:
        print(_("FAILED"))
        print_wrapped(_("ffmpeg is not found in current $PATH."))
        exit(1)
    print(_("OK"))

    print(_("Checking libmagic installation..."), end="", flush=True)
    try:
        import magic
    except ImportError:
        print(_("FAILED"))
        print_wrapped(_("libmagic is not found in your system."))
        exit(1)
    print(_("OK"))

    print(_("Checking libwebp installation..."), end="", flush=True)
    Image.init()
    if 'WEBP' not in Image.ID or not getattr(WebPImagePlugin, "SUPPORTED", None):
        print(_("FAILED"))
        print_wrapped(_("libwebp plugin is not detected by Pillow."))
        exit(1)
    print(_("OK"))

    print()


def wizard(profile, instance_id):
    data = DataModel(profile, instance_id)

    prerequisites_check()

    print_wrapped(_(
        "================================\n"
        "EFB Telegram Master Setup Wizard\n"
        "================================\n"
        "\n"
        "This wizard will guide you to setup your EFB Telegram Master channel "
        "(ETM). This would be really fast and simple."
    ))
    print()
    setup_proxy(data)
    setup_telegram_bot(data)
    setup_telegram_bot_commands_list(data)
    setup_admins(data)
    setup_experimental_flags(data)
    setup_network_configurations(data)
    setup_rpc(data)

    print(_("Saving configurations..."), end="", flush=True)
    data.save()
    print(_("OK"))

    print()
    print_wrapped(_(
        "Congratulations! You have finished the setup wizard for EFB Telegram "
        "Master Channel."
    ))
