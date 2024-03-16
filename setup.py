from setuptools import setup

with open('README.md', 'r', encoding='utf-8') as f:
    long_description = f.read()

setup(
    name='AsyncIRCClient',
    version='1.0.0',
    description='Async IRC Client',
    long_description=long_description,
    long_description_content_type='text/markdown',
    author='CoreTaxxe',
    author_email='coretaxxe@gmail.com',
    packages=['async_irc_client'],
    install_requires=[
        "loguru",
        "python_socks"
    ],
)