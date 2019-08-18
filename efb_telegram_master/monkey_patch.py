from telegram.vendor.ptb_urllib3.urllib3 import fields as ptb_fields
from urllib3.fields import format_header_param_html5


def load_monkey_patches():
    # ptb.vendor.urllib3 replace RFC2231 field names with HTML5 field names
    ptb_fields.format_header_param = format_header_param_html5
