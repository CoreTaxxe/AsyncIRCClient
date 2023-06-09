from setuptools import setup

setup(
    name='AsyncIRCClient',
    version='0.0.1',
    description='Async IRC Client',
    author='CoreTaxxe',
    author_email='coretaxxe@gmail.com',
    packages=['async_irc_client'],
    install_requires=[
        "loguru"
    ],
)