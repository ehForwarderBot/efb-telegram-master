
EFB Telegram 主端（ETM）
************************

.. image:: https://img.shields.io/pypi/v/efb-telegram-master.svg
   :target: https://pypi.org/project/efb-telegram-master/
   :alt: PyPI release

.. image:: https://d322cqt584bo4o.cloudfront.net/ehforwarderbot/localized.svg
   :target: https://crowdin.com/project/ehforwarderbot/
   :alt: Translate this project

.. image:: https://github.com/blueset/efb-telegram-master/blob/master/banner.png
   :alt: Banner

`其他语言的 README <./readme_translations>`_。

**信道 ID**: ``blueset.telegram``

ETM 是一个用于 EH Forwarder Bot 的 Telegram 主端，基于 Telegram Bot
API，``python-telegram-bot`` 建立。


测试版
======

该从端非稳定版本，且其功能随时可能会被更改。


依赖
====

* Python >= 3.6

* EH Forwarder Bot >= 2.0.0

* ffmpeg

* libmagic

* libwebp


使用步骤
========

1. 安装所需的依赖

2. 安装 ETM

    ::
       pip3 install efb-telegram-master

3. 在配置档案中的 ``config.yaml`` 中启用 ETM。

    根据您的个人配置档案，目录路径可能有所不同。

    **（在 EFB 2.0.0a1 中: 默认的配置档案储存目录位于**
    ``~/.ehforwarderbot/profiles/default`` **）**

1. 配置信道（步骤如下）


其他安装方式
------------

社区也贡献了其他的 ETM 安装方式，包括：

* `KeLiu <https://github.com/specter119>`_ 维护的 `AUR 软件包
  <https://aur.archlinux.org/packages/python-efb-telegram-master-git>`_
  (``python-efb-telegram-master-git``)

* 其他\ `安装脚本和容器（Docker 等）
  <https://github.com/blueset/ehForwarderBot/wiki/Channels-Repository#scripts-and-containers-eg-docker>`_


配置
====


设置机器人
----------

使用 `@BotFather <https://t.me/botfather>`_ 创建一个
bot，并给它起个名字及用户名。此后您会获得一个令牌（token）。此令牌稍后将会用到。请妥善保管该令牌，泄露该令牌相当于泄露 bot
的完整控制权限。

使用 ``/setjoingroups`` 来允许您的 bot 加入群组。使用 ``/setprivacy``
来禁用隐私限制，以使其能读取群组内的所有消息。


编写配置文件
------------

配置文件存储在 ``<配置档案目录>/blueset.telegram/config.yaml`` 上。

配置范例：

::

   ##################
   # Required items #
   ##################

   # [Bot Token]
   # This is the token you obtained from @BotFather
   token: "012345678:1Aa2Bb3Vc4Dd5Ee6Gg7Hh8Ii9Jj0Kk1Ll2M"

   # [List of Admin User IDs]
   # ETM will only process messages and commands from users
   # listed below. This ID can be obtained from various ways
   # on Telegram.
   admins:
   - 102938475
   - 91827364

   ##################
   # Optional items #
   ##################
   # [Experimental Flags]
   # This section can be used to toggle experimental functionality.
   # These features may be changed or removed at any time.
   # Options in this section is explained afterward.
   flags:
       option_one: 10
       option_two: false
       option_three: "foobar"

   # [Network Configurations]
   # [RPC Interface]
   # Refer to relevant sections afterwards for details.


用法
====

开始时，来自任意发送者的消息将被直接发往用户，也就是说，所有消息都会被混到一起。通过绑定会话，您可以将来自特定发送者的消息导向至一个空群组中，以更好地管理消息。

总而言之，ETM 提供了以下命令，您也可以将它们发送给 BotFather 以生成一个命令列表:

::

   help - Show commands list.
   link - Link a remote chat to a group.
   unlink_all - Unlink all remote chats from a group.
   info - Display information of the current Telegram chat.
   chat - Generate a chat head.
   extra - Access additional features from Slave Channels.
   update_info - Update the group name and profile picture.
   react - Send a reaction to a message, or show a list of reactors.

注解: 当指定了多个管理员时，所有管理员皆可以您的身份发送消息。但只有第 0 个管理员可以收到 bot 的私信。


``/link``：绑定会话
-------------------

1. 创建一个新群组，将您的 bot 邀请至群组中

2. 向 bot 直接发送 ``/link`` 命令，接着选择您想绑定的从端会话。

3. 点击「绑定」并选择您的新群组。*您也可以在该菜单中选择解绑或重绑会话*

4. 点击屏幕底部的「开始」按钮，接着你会看到一条「绑定成功」提示。

注解: 您可以邀请非 ETM 管理员加入群组中，但是：

   * 他/她们可以看到所有从相关远端会话发来的消息；

   * 他/她们不能够以您的名义发送消息。

如果「绑定」按钮无法工作，您可以尝试使用「手动绑定/重新绑定」按钮。手动绑定远程会话的步骤：

1. 将 bot 添加到您想要绑定至的群组

2. 复制由 bot 提供的代码，并将其发送至目标群组。

3. 如果绑定成功，您将从 bot 处收到一条成功提示。

此外，您也可以将 ``/unlink_all`` 发送至一个群组中以解绑其中的所有会话。


高级功能：筛选
~~~~~~~~~~~~~~

如果你的会话太多，不想在一次次点击 ``下一页 >`` 按钮，亦或是你想要一个更直接的方式筛选你的会话，ETM 为 ``/chat`` 和
``/list`` 指令搭载了筛选功能。在指令后面追加关联词，即可获得筛选后的会话列表。

例如：``/chat Eana`` 指令能够筛选出所有包含「Eana」的会话。

技术细节: 筛选的关键词实际上是一个正则表达式。 筛选过程中使用了 Python 的 ``re.search``，并开启了
``re.DOTALL | re.IGNORECASE`` 开关。即：``.`` 匹配包括换行符在内的所有字符、并且不区分大小写。
正则表达式在匹配时参照了以下格式的字符串，以便筛选多重条件。

::

   Channel: <Channel name>
   Name: <Chat name>
   Alias: <Chat Alias>
   ID: <Chat Unique ID>
   Type: (User|Group)
   Mode: [Linked]
   Other: <Python Dictionary String>

注解: Type（类型）可以是「User」（私聊）或「Group」（群组）。Other（其他）对应的是从端提供的「供应商特定」信息。相关数据的具体格式请参照相应项目的文档。

示例：

* 筛选所有微信（WeChat）群组：``Channel: WeChat.*Type: Group``

* 筛选所有具有别名的会话：``Name: (.*?)\nAlias: (?!\1)``

* 搜索所有同时包含「John」和「Johnny」的条目，不分先后：``(?=.*John)(?=.*Johnny)``


发送消息
--------


发送至已绑定的会话
~~~~~~~~~~~~~~~~~~

您可以像在普通 Telegram 会话中一样地发送消息。

支持的消息类型：

* 以任何受支持的格式发送/转发消息

* 直接回复消息

* 使用 inline bot 以任何受支持的格式发送消息

不支持的消息类型：

* @ 引用

* Markdown/HTML 格式

* 发送不受支持类型的消息


发送至未绑定的会话
~~~~~~~~~~~~~~~~~~

若要发送消息到未绑定的会话中，您必须「直接回复」以前的消息。或相应的「会话头」消息。 这些消息只会出现在您与 bot 的会话中。

在未绑定的会话中，直接回复的引用将不会被发送至远端信道，除此之外，受支持的内容皆与已绑定会话类似。


编辑和删除消息
~~~~~~~~~~~~~~

在 EFB v2 中，框架与 ETM 皆添加了对编辑和删除信息的支持。但由于 Telegram Bot API
的限制，即使您在删除消息时选择「从 bot 处撤回」或是「从所有成员的记录中撤回」，bot
也无法收到相关通知。因此，如果您想要删除您发送到远端会话中的某条消息，请编辑您的消息，并在开头加上 rm`（注意，是 R，M 和
~`，不是单引号），由此让 bot 知道您想要删除这条消息。

请注意：由于平台不同，部分信道可能不支持编辑或删除已发送的消息。


``/chat``：会话头
~~~~~~~~~~~~~~~~~

如果您想要将消息发送至一个无会话记录的未绑定的会话中，您可以让 ETM 生成一个「会话头」。
会话头的使用方式和您平时接收到的消息类似，只需对其回复便可向目标发送消息。

向 bot 发送 ``/chat`` 命令，接着在列表中选择一个会话。当您看见「回复该消息以与…对话。」字样时，就可以使用了。


高级功能：筛选
""""""""""""""

筛选也可以在 ``/chat`` 指令上使用。 请参阅前述章节 ``/link`` 的内容以获取详情。


``/extra``：从端提供的指令（附加功能）
--------------------------------------

部分从端会提供各种指令来操纵从端账号，并达成各种其他功能。这些指令被称为「附加功能」。您可以发送 ``/extra``
来查看从端提供的附加功能一览表。

附加功能的指令名称形如「``/<数字>_<指令名称>``」，且能够像 CLI 工具一样调用。（当然，管道 (piping)
等高级功能不会被支持）


``/update_info``：更新绑定群组的名称与头像
------------------------------------------

ETM 可以一键更新群组的名称和头像，和其所绑定的会话一致。

此功能仅在满足以下条件的情况下可用：

* 该命令发送于群组

* Bot 是该群组的管理员。

* 该群组\ **仅绑定到了一个**\ 远端会话

* 远端会话当前可用

从端如果没有提供会话的头像，群组的头像将不会被改变。


``/react``：向一条消息作出回应，或列出回应者列表
------------------------------------------------

向一条消息回复\ ``/react``\ 来显示对此消息做出过反应的成员列表，及所有反应的列表。

向一条消息回复跟有 emoji 的\ ``/react``\ 可以对此消息作出反应，例如\ ``/react 👍``。发送\
``/react -``\ 可以删除您的反应。

注意，一些从端可能不支持对消息的反应，而一些频道可能会限定您可以发送的反应。通常当您发送一个未被支持的反应时，从端可以提供一个反应列表供您选择尝试。


Telegram 频道支持
-----------------

ETM 提供了不完整的 Telegram 频道绑定支持。

ETM 可以：

* 绑定一个或多个远端会话到 Telegram 频道

* 查看和管理频道的绑定状态

* 一键更换频道的头像与名称

ETM 不能：

* 处理您或其他人发送给频道的消息

* 在频道中接受命令

目前，ETM 仅对以下的指令提供频道支持：

* ``/start`` 用于手动会话绑定

* ``/link`` 用于管理频道上绑定的会话

* ``/info`` 用于展示频道相关信息

* ``/update_info`` 用于更新频道名称与头像

使用方法：

1. 将 bot 添加到频道管理员列表

2. 在频道中发送指令

3. 将发送的指令转发到 bot 私信会话

技术细节: Telegram Bot API prevents bot from knowing who actually sent a
message in a channel (not including signatures as that doesn’t reflect
the numeric ID of the sender). In fact, that is the same for normal
users in a channel too, even admins. Thus, we think that it is not
safe to process messages directly from a channel.


局限性
======

由于 Telegram Bot API 和 EH Forwarder Bot 的技术限制，ETM 存在一些限制：

* **不支持**\ 部分 Telegram 消息类型：
     * 游戏消息

     * 发票（invoice，又译「账单」、「订单」）消息

     * 支付消息

     * 「通行证」（Passport）消息

     * 投票消息

* Telegram 消息中的部分细节被忽略：
     * 转发消息的原作者与签名

     * 消息格式、链接和消息预览

     * 消息附带的按钮

     * 消息所使用的 inline bot

* 来自从端消息部分细节被忽略：
     * @ 引用。

* 本 Telegram bot 只能够：
     * 向您发送最大 50 MiB 的文件

     * 接受您发来的最大 20 MiB 的文件


实验性功能
==========

以下的实验性功能随时可能被更改或被删除，请自行承担相关风险。

使用功能可以在配置文件的 ``flags`` 一节中启用，例如：

::

   flags:
       flag_name: flag_value

* ``chats_per_page`` *(int)* [默认: ``10``]

  在触发 ``/chat`` 和 ``/link`` 指令是每页显示的条目数。 过大的数值可能会导致该功能失效。

* ``network_error_prompt_interval`` *(int)* [默认: ``100``]

  每发生 ``n`` 次网络连接错误时通知用户一次。 设置为 0 即可禁用。

* ``multiple_slave_chats`` *(bool)* [默认: ``true``]

  绑定多个会话到一个 Telegram 群组。 消息发送方式与未绑定群组相同。 禁用后 ETM 会强制远端回话与 Telegram
  群组一对一绑定。

* ``prevent_message_removal`` *(bool)* [默认: ``true``]

  当从端要求删除特定消息时，ETM 将以通知替代删除操作。

* ``auto_locale`` *(str)* [默认: ``true``]

  从 bot 管理员的语言设定中自动设定 ETM 语言。 当该值为 ``false`` 时，ETM 会从系统的环境变量中读取语言设定。

* ``retry_on_error`` *(bool)* [默认: ``false``]

  当向 Telegram Bot API 发送请求出错时，一直重试请求。 注意：由于 Telegram Bot API
  的应答可能不稳定，这可能导致重复的消息传送出现重复，且可能导致您看到的结果与实际不符。

* ``send_image_as_file`` *(bool)* [默认: ``false``]

  将所有图片消息以文件发送，以积极避免 Telegram 对于图片的压缩。

* ``message_muted_on_slave`` *(str)* [Default: ``normal``]

  Behavior when a message received is muted on slave channel platform.

  * ``normal``: send to Telegram as normal message

  * ``silent``: send to Telegram as normal message, but without
    notification sound

  * ``mute``: do not send to Telegram

* ``your_message_on_slave`` *(str)* [Default: ``silent``]

  Behavior when a message received is from you on slave channel
  platform. This overrides settings from ``message_muted_on_slave``.

  * ``normal``: send to Telegram as normal message

  * ``silent``: send to Telegram as normal message, but without
    notification sound

  * ``mute``: do not send to Telegram


Network configuration: timeout tweaks
=====================================

   This chapter is adapted from `Python Telegram Bot wiki
   <https://github.com/python-telegram-bot/python-telegram-bot/wiki/Handling-network-errors#tweaking-ptb>`_,
   licensed under CC-BY 3.0.

``python-telegram-bot`` performs HTTPS requests using ``urllib3``.
``urllib3`` provides control over ``connect_timeout`` &
``read_timeout``. ``urllib3`` does not separate between what would be
considered read & write timeout, so ``read_timeout`` serves for both.
The defaults chosen for each of these parameters is 5 seconds.

The ``connect_timeout`` value controls the timeout for establishing a
connection to the Telegram server(s).

Changing the defaults of ``read_timeout`` & ``connet_timeout`` can be
done by adjusting values ``request_kwargs`` section in ETM’s \
``config.yaml``.

::

   # ...
   request_kwargs:
       read_timeout: 6
       connect_timeout: 7


Run ETM behind a proxy
======================

   This chapter is adapted from `Python Telegram Bot wiki
   <https://github.com/python-telegram-bot/python-telegram-bot/wiki/Working-Behind-a-Proxy>`_,
   licensed under CC-BY 3.0.

You can appoint proxy specifically for ETM without affecting other
channels running in together in the same EFB instance. This can also
be done by adjusting values ``request_kwargs`` section in ETM’s \
``config.yaml``.


HTTP proxy server
-----------------

::

   request_kwargs:
       # ...
       proxy_url: http://PROXY_HOST:PROXY_PORT/
       # Optional, if you need authentication:
       username: PROXY_USER
       password: PROXY_PASS


SOCKS5 proxy server
-------------------

This is configuration is supported, but requires an optional/extra
python package. To install:

::

   pip install python-telegram-bot[socks]

::

   request_kwargs:
       # ...
       proxy_url: socks5://URL_OF_THE_PROXY_SERVER:PROXY_PORT
       # Optional, if you need authentication:
       urllib3_proxy_kwargs:
           username: PROXY_USER
           password: PROXY_PASS


RPC interface
=============

A standard `Python XML RPC server
<https://docs.python.org/3/library/xmlrpc.html>`_ is implemented in
ETM 2. It can be enabled by adding a ``rpc`` section in ETM’s
``config.yml`` file.

::

   rpc:
       server: 127.0.0.1
       port: 8000

警告: The ``xmlrpc`` module is not secure against maliciously
   constructed data. Do not expose the interface to untrusted
   parties or the public internet, and turn off after use.


Exposed functions
-----------------

Functions in `the db (database manager) class
<https://github.com/blueset/efb-telegram-master/blob/master/efb_telegram_master/db.py>`_
and \ `the RPCUtilities class
<https://github.com/blueset/efb-telegram-master/blob/master/efb_telegram_master/rpc_utilities.py>`_
are exposed. Refer to the source code for their documentations.


How to use
----------

Set up a ``SimpleXMLRPCClient`` in any Python script and call any of
the exposed functions directly. For details, please consult `Python
documentation on xmlrpc
<https://docs.python.org/3/library/xmlrpc.html>`_.


实验性翻译支持
==============

ETM 启用了实验性的本地化翻译。本 bot 能够从管理员的语言设定中自动检测，并设置为一种已支持的语言。如果您不希望使用测功能，您可以
关闭 ``auto_locale`` 功能，并将语言环境变量
(``LANGUAGE``、``LC_ALL``、``LC_MESSAGES`` 或 ``LANG``) 设置为一种设为一种已支持的语言。
同时，您也可以在我们的 `Crowdin 项目
<https://crowdin.com/project/ehforwarderbot/>`_\ 里面将 EWS 翻译为您的语言。
