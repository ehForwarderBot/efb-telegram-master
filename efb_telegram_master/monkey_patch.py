def patch_ptb_urllib3():
    # ptb.vendor.ptb_urllib3 replace RFC2231 field names with HTML5 field names
    # Enclosed in a try-except block to prevent code breaking when ptb is installed
    # from Arch package repository.
    #
    # See https://github.com/blueset/efb-telegram-master/issues/68.
    try:
        from telegram.vendor.ptb_urllib3.urllib3 import fields as ptb_fields
        from urllib3.fields import format_header_param_html5

        ptb_fields.format_header_param = format_header_param_html5
    except ImportError:
        pass


def load_monkey_patches():
    patch_ptb_urllib3()
