
EFB Telegram 主端（ETM）
************************

.. image:: https://img.shields.io/pypi/v/efb-telegram-master.svg
   :target: https://pypi.org/project/efb-telegram-master/
   :alt: PyPI release

.. image:: https://github.com/ehForwarderBot/efb-telegram-master/workflows/Tests/badge.svg
   :target: https://github.com/ehForwarderBot/efb-telegram-master/actions
   :alt: Tests status

.. image:: https://pepy.tech/badge/efb-telegram-master/month
   :target: https://pepy.tech/project/efb-telegram-master
   :alt: Downloads per month

.. image:: https://d322cqt584bo4o.cloudfront.net/ehforwarderbot/localized.svg
   :target: https://crowdin.com/project/ehforwarderbot/
   :alt: Translate this project

.. image:: https://github.com/ehForwarderBot/efb-telegram-master/raw/master/banner.png
   :alt: Banner

`其他語言的 README <./readme_translations>`_。

**頻道 ID**: ``blueset.telegram``

ETM 是一個用於 EH Forwarder Bot 的 Telegram 主端，基於 Telegram Bot
API，``python-telegram-bot`` 建立。


依賴
====

* Python >= 3.6

* EH Forwarder Bot >= 2.0.0

* ffmpeg

* libmagic

* libwebp


使用步驟
========

1. 安裝所需的依賴

2. 安裝 ETM

    ::
       pip3 install efb-telegram-master

3. 使用 *EFB 配置嚮導* 啟用和配置 ETM，或在配置檔案的 ``config.yaml`` 中手動啟用。

    根據您的個人配置檔案，目錄路徑可能有所不同。

    **（在 EFB 2 中: 預設的配置檔案儲存目錄位於**
    ``~/.ehforwarderbot/profiles/default`` **）**

4. 配置主端（手動配置說明如下）


其他安裝方式
------------

社群也貢獻了其他的 ETM 安裝方式，包括：

* `KeLiu <https://github.com/specter119>`_ 維護的 `AUR 套裝軟體
  <https://aur.archlinux.org/packages/python-efb-telegram-master-git>`_
  (``python-efb-telegram-master-git``)

* 其他\ `安裝腳本和容器（Docker 等）
  <https://efb-modules.1a23.studio#scripts-and-containers-eg-docker>`_


手動配置
========


設定機器人
----------

使用 `@BotFather
<https://t.me/botfather>`_ 建立一個 bot，並給它取個名字及使用者名稱。此後您會獲得一個令牌（token）。此令牌稍後將會用到。請妥善保管該令牌，洩露該令牌相當於洩露 bot 的完整控制權限。

使用 ``/setjoingroups`` 來允許您的 bot 加入群組。使用 ``/setprivacy``
來禁用隱私限制，以使其能讀取群組內的所有消息。


編寫配置檔案
------------

配置檔案儲存在 ``<配置檔案目錄>/blueset.telegram/config.yaml`` 上。

配置範例：

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

開始時，來自任意發送者的消息將被直接發往使用者，也就是說，所有消息都會被混到一起。透過綁定對話，您可以將來自特定發送者的消息導向至一個空群組中，以更好地管理消息。

總而言之，ETM 提供了以下指令，您也可以將它們發送給 BotFather 以生成一個命令列表:

::

   help - Show commands list.
   link - Link a remote chat to a group.
   unlink_all - Unlink all remote chats from a group.
   info - Display information of the current Telegram chat.
   chat - Generate a chat head.
   extra - Access additional features from Slave Channels.
   update_info - Update info of linked Telegram group.
   react - Send a reaction to a message, or show a list of reactors.
   rm - Remove a message from its remote chat.

備註: 當指定了多個管理員時，所有管理員皆可以您的身份發送消息。但只有第 0 個管理員可以收到 bot 的私信。


``/link``：綁定對話
-------------------

1. 建立一個新群組，將您的 bot 邀請至群組中

2. 向 bot 直接發送 ``/link`` 指令，接著選擇您想綁定的從端對話。

3. 點擊「綁定」並選擇您的新群組。*您也可以在該選單中選擇解綁或重綁對話*

4. 點擊螢幕底部的「開始」按鈕，接著你會看到一條「綁定成功」提示。

備註: 您可以邀請非 ETM 管理員加入群組中，但是：

   * 他/她們可以看到所有從相關遠端對話發來的消息；

   * 他/她們不能夠以您的名義發送消息。

如果「綁定」按鈕無法工作，您可以嘗試使用「手動綁定/重新綁定」按鈕。手動綁定遠端對話的步驟：

1. 將 bot 添加到您想要綁定至的群組

2. 複製由 bot 提供的程式碼，並將其發送至目標群組。

3. 如果綁定成功，您將從 bot 處收到一條成功提示。

此外，您也可以將 ``/unlink_all`` 發送至一個群組中以解綁其中的所有對話。

此外，如果您想要綁定您之前使用的對話，您可以簡單地回覆 ``/link`` 引用一條以往來自該消息，而不從漫長的對話列表中選擇。


進階功能：篩選
~~~~~~~~~~~~~~

如果你的對話太多，不想在一次次點擊 ``下一頁
>`` 按鈕，亦或是你想要一個更直接的方式篩選你的對話，ETM 為 ``/chat`` 和 ``/list`` 指令搭載了篩選功能。在指令後面追加關聯詞即可獲得篩選後的對話列表。

例如：``/chat Eana`` 指令能夠篩選出所有包含「Eana」的對話。

技術細節: 篩選的關鍵字實際上是一個正規表示式。 篩選過程中使用了 Python 的 ``re.search``，並開啟了
``re.DOTALL | re.IGNORECASE`` 開關。即：``.`` 匹配包括換行符在內的所有字元、並且不區分大小寫。
正規表示式在匹配時參照了以下格式的字串，以便篩選多重條件。

::

   Channel: <Channel name>
   Channel ID: <Channel ID>
   Name: <Chat name>
   Alias: (<Chat Alias>|None)
   ID: <Chat Unique ID>
   Type: (Private|Group|System)
   Mode: [Linked]
   Description: <Description>
   Notification: (ALL|MENTION|NONE)
   Other: <Python Dictionary String>

備註: Type（類型）可以是「User」（私聊）或「Group」（群組）。Other（其他）對應的是從端提供的「供應商特定」訊息。相關資料的具體格式請參照相應項目的文件。

範例：

* 篩選所有微信（WeChat）群組：``Channel: WeChat.*Type: Group``

* 尋找所有沒有備註名稱（或備註名稱為「None」）的對話：``Alias: None``

* 搜尋所有同時包含「John」和「Johnny」的條目，不分先後：``(?=.*John)(?=.*Johnny)``


發送消息
--------


發送至已綁定的對話
~~~~~~~~~~~~~~~~~~

您可以像在普通 Telegram 對話中一樣地發送消息。

支援的消息類型：

* 以任何受支援的格式發送/轉發消息

* 引用回覆消息

* 使用 inline bot 以任何受支援的格式發送消息

不支援的消息類型：

* @ 引用

* Markdown/HTML 格式

* 消息內附按鈕

* 不受支援類型的消息。

備註: 這僅適用於單獨綁定（僅綁定到一個遠端對話）的 Telegram 群組。在綁定多個遠端對話的群組中的操作方式應未綁定對話的相同。


發送至未綁定的對話
~~~~~~~~~~~~~~~~~~

若要發送消息到未綁定的對話中，您必須「引用回覆」以前的消息。或相應的「對話頭」消息。 這些消息只會出現在您與 bot 的對話中。

在未綁定的對話中，回覆中的引用將不會被發送至遠端頻道，除此之外，受支援的內容皆與已綁定對話類似。


在未綁定的對話中快速回覆
""""""""""""""""""""""""

ETM 提供了一種機制，允許您在不每次引用回覆的情況下向同一收件人發送消息。
ETM 會儲存您在每個 Telegram 對話（即 Telegram 群組或 bot）中發出訊息對應的遠端收信對話。該遠端對話被稱為此 Telegram 對話的「最後一個已知收件人」。

如果消息未指定收件人， ETM 僅會在滿足以下條件時將起發送至該 Telegram 對話中的「最後一個已知收件人」：

1. 您在過去一小時內與「最後一個已知收件人」有過通信，並且

2. 該 Telegram 對話中最新一條消息來自於該「最後一個已知收件人」。


編輯和刪除消息
~~~~~~~~~~~~~~

在 EFB v2 中，框架與 ETM 皆添加了對編輯和刪除訊息的支援。但由於 Telegram Bot
API 的限制，即使您在刪除消息時選擇「從 bot 處撤回」或是「從所有成員的紀錄中撤回」，bot 也無法收到相關通知。因此，如果您想要刪除您發送到遠端對話中的某條消息，請編輯您的消息，並在開頭加上 ``rm```（注意，是 ``R``、``M`` 和 ，``~```，不是單引號），由此讓 bot 知道您想要刪除這條消息。

或者，您也可以向這條消息回覆 ``/rm`` 來將其從遠端對話中移除。
此方法可以用於消息不能直接被編輯（如貼紙、位置等），或消息不是透過 ETM 發送的情況。

請注意：由於平台不同，部分從端可能不支援編輯或刪除已發送的消息。


``/chat``：對話頭
~~~~~~~~~~~~~~~~~

如果您想要將消息發送至一個無對話記錄的未綁定的對話中，您可以讓 ETM 生成一個「對話頭」。
對話頭的使用方式和您平時接收到的消息類似，只需對其回覆便可向目標發送消息。

向 bot 發送 ``/chat`` 指令，接著在列表中選擇一個對話。當您看見「回覆該消息以與…對話。」字樣時，就可以使用了。


進階功能：篩選
""""""""""""""

篩選也可以在 ``/chat`` 指令上使用。 請參閱前述章節 ``/link`` 的內容以了解詳情。


``/extra``：從端提供的指令（附加功能）
--------------------------------------

部分從端會提供各種指令來操縱從端帳號，並達成各種其他功能。這些指令被稱為「附加功能」。您可以發送 ``/extra``
來查看從端提供的附加功能一覽表。

附加功能的指令名稱形如「``/<數字>_<指令名稱>``」，且能夠像 CLI 工具一樣呼叫。（當然，管道 (piping)
等進階功能不會被支援）


``/update_info``：更新被綁定 Telegram 群組的詳情訊息
----------------------------------------------------

ETM 可以協助您依照遠端對話來更新 Telegram 群組的名稱和大頭貼。如果遠端對話是一個群組，ETM 還可以將群組的成員列表寫入 Telegram 對話的簡介中。

此功能僅在滿足以下條件的情況下可用：

* 該指令發送於群組

* Bot 是該群組的管理員。

* 該群組 **僅綁定到了一個** 遠端對話

* 遠端對話目前可用

從端如果沒有提供對話的大頭貼，群組的大頭貼將不會被改變。


``/react``：向一條消息作出回應，或列出回應者列表
------------------------------------------------

向一條消息回覆 ``/react`` 來顯示對此消息做出過回應的成員列表，及所有回應的列表。

向一條消息回覆跟有 emoji 的 ``/react`` 可以對此消息作出回應，例如 ``/react 👍``。發送 ``/react
-`` 可以刪除您的回應。

注意，一些從端可能不支援對消息的回應，而一些從端可能會限定您可以發送的回應。通常當您發送一個未被支援的回應時，從端可以提供一個回應列表供您選擇嘗試。


``/rm``：從遠端對話中刪除消息
-----------------------------

向一條消息回覆 ``/rm`` 即可在遠端對話中移除該消息。比起在消息內容之前追加 ``rm``` 的功能，本方法可以在您不能直接編輯消息（如貼紙、位置等）、或是沒有透過 ETM 發送消息時移除這些消息。
在從端允許的情況下，該指令還能嘗試移除其他人發送的消息。

請注意：由於平台不同，部分從端可能不支援刪除已發送的消息。


Telegram 頻道支援
-----------------

ETM 提供了不完整的 Telegram 頻道綁定支援。

ETM 可以：

* 綁定一個或多個遠端對話到 Telegram 頻道

* 查看和管理頻道的綁定狀態

* 一鍵更換頻道的大頭貼與名稱

ETM 不能：

* 處理您或其他人發送給頻道的消息

* 在頻道中接受指令

目前，ETM 僅對以下的指令提供頻道支援：

* ``/start`` 用於手動對話綁定

* ``/link`` 用於管理頻道上綁定的對話

* ``/info`` 用於展示頻道相關訊息

* ``/update_info`` 用於更新頻道名稱與大頭貼

使用方法：

1. 將 bot 添加到頻道管理員列表

2. 在頻道中發送指令

3. 將發送的指令轉發到 bot 私信對話

技術細節: Telegram Bot API
阻止機器人獲知在頻道內實際發送消息的使用者訊息。（不包括簽名，因為簽名不能反映發送者的數字ID）事實上，對於一個頻道中的普通使用者（包括管理員）來說亦是如此。如果要無條件處理來自頻道的消息，不僅現有頻道中的其他管理員可以向其添加惡意管理員，Telegram
上的任何人一旦知道您的 bot 使用者名稱，就可以將其添加到頻道並以您的身份使用該 bot。因此，我們認為直接從頻道處理消息是不安全的。


局限性
======

由於 Telegram Bot API 和 EH Forwarder Bot 的技術局限，ETM 存在一些限制：

* **不支援**部分 Telegram 消息類型：
     * 遊戲消息

     * 發票（invoice，又譯「帳單」、「訂單」）消息

     * 支付消息

     * 「通行證」（Passport）消息

     * 投票消息

* ETM 無法處理來自另一個 Telegram bot 的任何消息。

* Telegram 消息中的部分細節被忽略：
     * 轉發消息的原作者與簽名

     * 消息格式、連結和消息預覽

     * 消息附帶的按鈕

     * 消息所使用的 inline bot

* 來自從端消息部分細節被忽略：
     * 沒有提及您的 @ 引用。

* 本 Telegram bot 只能夠：
     * 向您發送最大 50 MB 的文件

     * 接受您發來的最大 20 MB 的文件


實驗性功能
==========

以下的實驗性功能隨時可能被更改或被刪除，請自行承擔相關風險。

使用功能可以在配置檔案的 ``flags`` 一節中啟用，例如：

::

   flags:
       flag_name: flag_value

* ``chats_per_page`` *(int)* [預設: ``10``]

  在觸發 ``/chat`` 和 ``/link`` 指令是每頁顯示的條目數。 過大的數值可能會導致該功能失效。

* ``network_error_prompt_interval`` *(int)* [預設: ``100``]

  每發生 ``n`` 次網路連接錯誤時通知使用者一次。 設定為 0 即可禁用。

* ``multiple_slave_chats`` *(bool)* [預設: ``true``]

  綁定多個對話到一個 Telegram 群組。 消息發送方式與未綁定群組相同。 禁用後 ETM 會強制遠端回話與 Telegram
  群組一對一綁定。

* ``prevent_message_removal`` *(bool)* [預設: ``true``]

  當從端要求刪除特定消息時，ETM 將以通知替代刪除操作。

* ``auto_locale`` *(str)* [預設: ``true``]

  從 bot 管理員的語言設定中自動設定 ETM 語言。當該值為 false 時，ETM 會從系統的環境變數中讀取語言設定。

* ``retry_on_error`` *(bool)* [預設: ``false``]

  當向 Telegram Bot API 發送請求出錯時，一直重試請求。 注意：由於 Telegram Bot API
  的應答可能不穩定，這可能導致重複的消息傳送出現重複，且可能導致您看到的結果與實際不符。

* ``send_image_as_file`` *(bool)* [預設: ``false``]

  將所有圖片消息以文件發送，以積極避免 Telegram 對於圖片的壓縮。

* ``message_muted_on_slave`` *(str)* [預設值：``normal``]

  當收到在從端平台上被靜音的消息時的行為。

  * ``normal``：作為普通消息發送到 Telegram

  * ``silent``：作為普通消息發送到 Telegram，但沒有通知聲音

  * ``mute``：不要發送到 Telegram

* ``your_message_on_slave`` *(str)* [預設值：``silent``]

  當收到由你在從端平台發送的消息時的行為。這項設定將覆蓋 ``message_muted_on_slave`` 選項

  * ``normal``：作為普通消息發送到 Telegram

  * ``silent``：作為普通消息發送到 Telegram，但沒有通知聲音

  * ``mute``：不要發送到 Telegram

* ``animated_stickers`` *(bool)* [預設值: ``false``]

  Enable experimental support to animated stickers. Note: you need to
  install binary dependency ``libcairo`` on your own, and additional
  Python dependencies via ``pip3 install "efb-telegram-master[tgs]"``
  to enable this feature.

* ``send_to_last_chat`` *(str)* [預設值: ``warn``]

  在未綁定的對話中快速回覆。

  * ``enabled``：啟用此功能並關閉警告。

  * ``warn``：啟用該功能，並在自動發送至不同收件人時發出警告。

  * ``disabled``：禁用此功能。

* ``default_media_prompt`` *(str)* [預設值：``emoji``]

  當圖片/影片/文件消息沒有標題時使用的占位符文字。

  * ``emoji``：使用 emoji， 如 🖼️、🎥 和 📄。

  * ``text``：使用文字，如「發送了圖片/影片/文件」。

  * ``disabled``：使用空占位符。

* ``api_base_url`` *(str)* [Default: ``null``]

  Base URL of the Telegram Bot API. Defaulted to
  ``https://api.telegram.org/bot``.

* ``api_base_file_url`` *(str)* [Default: ``null``]

  Base file URL of the Telegram Bot API. Defaulted to
  ``https://api.telegram.org/file/bot``.

* ``local_tdlib_api`` *(bool)* [Default: ``false``]

  Enable this option if the bot API is running in ``--local`` mode and
  is using the same file system with ETM.


網路配置：超時調整
==================

   本章內容修改自 `Python Telegram Bot wiki
   <https://github.com/python-telegram-bot/python-telegram-bot/wiki/Handling-network-errors#tweaking-ptb>`_，遵從
   CC-BY 3.0 許可。

``python-telegram-bot`` 使用 ``urllib3`` 執行 HTTPS 請求。``urlllib3``提供了對
``connect_timeout`` 和 ``read_timeout`` 的控制。``urllib3`` 不回區別讀超時和寫超時，所以
``read_timeout`` 同時對讀寫超時生效。各個參數的預設值均為 5 秒。

``connect_timeout`` 控制連接到 Telegram 伺服器的超時時長 。

可以透過調整 ETM 的 ``config.yaml`` 中的 ``request_kwargs`` 來更改 ``read_timeout`` 和 ``connect_timeout`` 的預設值。

::

   # ...
   request_kwargs:
       read_timeout: 6
       connect_timeout: 7


透過代理執行 ETM
================

   本章內容修改自 `Python Telegram Bot wiki
   <https://github.com/python-telegram-bot/python-telegram-bot/wiki/Working-Behind-a-Proxy>`_，遵從
   CC-BY 3.0 許可。

您可以為 ETM 單獨指定代理，而不會影響相同 EFB 實例下的其他頻道。您也可以透過調整 ETM 的 ``config.yaml`` 中的 ``request_kwargs`` 選項來完成此操作。


HTTP 代理伺服器
---------------

::

   request_kwargs:
       # ...
       proxy_url: http://PROXY_HOST:PROXY_PORT/
       # Optional, if you need authentication:
       username: PROXY_USER
       password: PROXY_PASS


SOCKS5 代理伺服器
-----------------

此設定已被支援，但需要安裝一個可選的/額外的 python 包。安裝方法：

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


RPC 介面
========

ETM 2 中實現了一個標準的 `Python XML RPC 伺服器
<https://docs.python.org/3/library/xmlrpc.html>`_。您可以透過在 ETM 的 ``config.yml`` 文件中添加 ``rpc`` 選項來啟用這一功能。

::

   rpc:
       server: 127.0.0.1
       port: 8000

警告: ``xmlrpc`` 元件對惡意構建的資料是不安全的。不要將此介面暴露給不被信任的當事方或公共網路，並在使用後應該關閉此介面。


提供的函數
----------

我們提供了 `db（資料庫管理器）類
<https://etm.1a23.studio/blob/master/efb_telegram_master/db.py>`_\ 和
`RPCUtilities 類
<https://etm.1a23.studio/blob/master/efb_telegram_master/rpc_utilities.py>`_\
中的函數。詳細文件請參考原始碼。


使用方法
--------

您可以在任意 Python 腳本中設定一個 ``SimpleXMLRPCClient``，並可以直接呼叫任何被暴露的函數。詳情請查閱
`Python 文件的 xmlrpc 章節
<https://docs.python.org/3/library/xmlrpc.html>`_。


設定 Webhook
============

有關如何設定 webhook 的詳細資訊，請瀏覽此 `wiki 文章
<https://github.com/ehForwarderBot/efb-telegram-master/wiki/Setup-Webhook>`_。


許可協議
========

ETM 使用了 `GNU Affero General Public License 3.0
<https://www.gnu.org/licenses/agpl-3.0.txt>`_ 或更新版本作為其開源許可:

::

   EFB Telegram Master Channel: A master channel for EH Forwarder Bot.
   Copyright (C) 2016 - 2020 Eana Hufwe, and the EFB Telegram Master Channel contributors
   All rights reserved.

   This program is free software: you can redistribute it and/or modify
   it under the terms of the GNU Affero General Public License as
   published by the Free Software Foundation, either version 3 of the
   License, or any later version.

   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.

   You should have received a copy of the GNU Affero General Public License
   along with this program.  If not, see <http://www.gnu.org/licenses/>.


支援翻譯
========

ETM 啟用了由社群支援的本地化翻譯。本 bot 能夠從管理員的語言設定中自動檢測，並設定為一種已支援的語言。如果您不希望使用測功能，您可以
關閉 ``auto_locale`` 功能，並將語言環境變數
(``LANGUAGE``、``LC_ALL``、``LC_MESSAGES`` 或 ``LANG``) 設定為一種設為一種已支援的語言。
同時，您也可以在我們的 `Crowdin 項目
<https://crowdin.com/project/ehforwarderbot/>`_\ 裡面將 EWS 翻譯為您的語言。

備註: 如果您使用原始碼安裝，您需要手動編譯翻譯字串文件（``.mo``）才可啟用翻譯後的介面。
