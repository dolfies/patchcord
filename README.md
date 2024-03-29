![Litecord logo](static/logo/logo.png)

Litecord is an open source, [clean-room design][clean-room] reimplementation of
Discord's HTTP API and Gateway in Python 3.

This project is a rewrite of [litecord-reference] and [litecord serviced].

Other than implementing various features, Patchcord aims to integrate client functionality and various QoL improvements into Litecord for educational purposes.  
Credits to [Displunger](https://gitlab.com/derpystuff/displunger).

[clean-room]: https://en.wikipedia.org/wiki/Clean_room_design
[litecord-reference]: https://gitlab.com/luna/litecord-reference
[litecord serviced]: https://github.com/litecord

## Important Note

This project is for educational purposes and open-sourced so other cool people can observe and improve the project in collaboration with us. Our instance is private and at this time we are not providing selfhosting support.

## Wait, two other Litecords?

The first version is litecord-reference, written in Python and used MongoDB
as storage. It was rewritten into "litecord serviced" so that other developers
could help writing it, defining a clear protocol between components
(litebridge). Sadly, it didn't take off, so I (Luna), that wrote the other two,
took a shot at writing it again. It works.

**This is "Litecord" / "litecord".** There are _no_ rewrites planned (for now :>).

## Project Goals

- Being able to unit test bots in an autonomous fashion.
- Doing research and exploration on the Discord API.
- Doing research on old clients and scrapped features.

## Caveats

- Unit testing is incomplete.
- Currently, there are no plans to support video in voice chats, or the
  Discord Store.
- Many things are non-performant, deviate from the Discord API, are incomplete, etc.
- Compatibility is preferred to accuracy. Because of this, many duplicate/deprecated fields exist in the API.

## Implementation status, AKA "Does it work?"

The following "core features" are implemented to an useful degree in Litecord:

- Guilds, Text Channels, Messages
- Roles, Channel Overwrites, Emojis
- Member Lists (from [lazy guilds](https://luna.gitlab.io/discord-unofficial-docs/lazy_guilds.html))

Tracking routes such as `/api/science` have dummy implementations.

Also consider that reimplementing the Discord API is a moving target, as
Discord can implement new features at any time, for any reason. The following
are not implemented, for example:

- Threads
- Auto moderation
- Server boosts

## Liability

We (Litecord and contributors) are not liable for usage of this software,
valid or invalid. If you intend to use this software as a "self-hostable
Discord alternative", you are solely responsible for any legal action delivered
by Discord if you are using their assets, intellectual property, etc.

All referenced material for implementation is based off of
[official Discord API documentation](https://discordapp.com/developers/docs)
or third party libraries (such as [Eris](https://github.com/abalabahaha/eris)).

## Installation

Requirements:

- **Python 3.9+**
- PostgreSQL (tested using 9.6+), SQL knowledge is recommended.
- gifsicle for GIF emoji and avatar handling
- [poetry]

Optional requirement:

- [mediaproxy]

[poetry]: https://python-poetry.org/
[mediaproxy]: https://gitlab.com/litecord/mediaproxy

### Download the code

```sh
$ git clone https://github.com/dolfies/patchcord.git && cd patchcord
```

### Install packages

```sh
$ poetry install
```

### Setting up the database

It's recommended to create a separate user for the `litecord` database.

```sh
# Create the PostgreSQL database.
$ createdb litecord
```

Copy the `config.example.py` file and edit it to configure your instance (
postgres credentials, etc):

```sh
$ cp config.example.py config.py
$ $EDITOR config.py
```

Then, you should run database migrations:

```sh
$ poetry run ./manage.py migrate
```

## Running

Hypercorn is used to run Litecord. By default, it will bind to `0.0.0.0:5000`.
This will expose your Litecord instance to the world. You can use the `-b`
option to change it (e.g. `-b 0.0.0.0:45000`).

```sh
$ poetry run hypercorn run:app
```

You can use `--access-log -` to output access logs to stdout.

**It is recommended to run litecord behind [NGINX].** You can use the
`nginx.conf` file at the root of the repository as a template.

[nginx]: https://www.nginx.com

### Does it work?

You can check if your instance is running by performing an HTTP `GET` request on
the `/api/v9/gateway` endpoint. For basic websocket testing, a tool such as
[ws](https://github.com/hashrocket/ws) can be used.

After checking that it actually works, `docs/operating.md` continues on common
operations for a Litecord instance.

## Updating

Update the code and run any new database migrations:

```sh
$ git pull
$ poetry run ./manage.py migrate
```

## Running tests

```sh
# Install tox:
$ pip install tox

# Run lints and tests:
$ tox
```
