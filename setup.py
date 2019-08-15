import sys
import os
from setuptools import setup, find_packages

if sys.version_info < (3, 6):
    raise Exception("Python 3.6 or higher is required. Your version is %s." % sys.version)

version_path = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                            'efb_telegram_master/__version__.py')

__version__ = ""
exec(open(version_path).read())

long_description = open('README.rst').read()

setup(
    name='efb-telegram-master',
    packages=find_packages(exclude=["*.tests", "*.tests.*", "tests.*", "tests"]),
    version=__version__,
    description='Telegram Master Channel for EH Forwarder Bot, based on Telegram Bot API.',
    long_description=long_description,
    author='Eana Hufwe',
    author_email='ilove@1a23.com',
    url='https://github.com/blueset/efb-telegram-master',
    license='AGPLv3+',
    include_package_data=True,
    python_requires='>=3.6',
    keywords=['ehforwarderbot', 'EH Forwarder Bot', 'EH Forwarder Bot Master Channel', 'Telegram',
              'Telegram Bot', 'chatbot'],
    classifiers=[
        "Development Status :: 4 - Beta",
        "License :: OSI Approved :: GNU Affero General Public License v3 or later (AGPLv3+)",
        "Intended Audience :: Developers",
        "Intended Audience :: End Users/Desktop",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Topic :: Communications :: Chat",
        "Topic :: Utilities"
    ],
    install_requires=[
        "ehforwarderbot>=2.0.0b18",
        "python-telegram-bot>=10.0.0,<12.0.0",
        "python-magic",
        "moviepy",
        "peewee",
        "requests",
        "pydub",
        "ruamel.yaml",
        "pillow",
        "language-tags",
        "retrying",
    ],
    entry_points={
        "ehforwarderbot.master": "blueset.telegram = efb_telegram_master:TelegramChannel",
        "ehforwarderbot.wizard": "blueset.telegram = efb_telegram_master.wizard:wizard"
    }
)
