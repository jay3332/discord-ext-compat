# discord-ext-compat
Adds support for application commands without needing a major codebase rewrite for the ``ext.commands`` framework.

## Installation
Currently this can only be installed through GitHub, although I plan to publish it on PyPI soon:

```shell 
$ pip install -U git+https://github.com/jay3332/discord-ext-compat
```

Requires Python 3.8+.

## Getting Started
By default, discord-ext-compat does not automatically monkeypatch methods for you; you must manually call the `monkeypatch()` function:
```py
from discord.ext.compat import monkeypatch

monkeypatch()
```
Note that the call must come BEFORE other imports.

If you are new to Python or don't really understand what monkeypatching is, then this function is probably not for you.

### Compatibility without monkeypatching?
Monkeypatching is completely optional and not encouraged at all as at the end of the day, it's still monkeypatching.

You can manually add support for this module by:
1. Adding the ``CompatMixin`` mixin as a mixin to your ``Bot`` or ``AutoShardedBot`` class. Note that you MUST put this mixin FIRST in the resolution order, e.g. ``class Bot(CompatMixin, commands.Bot)``. Order here strictly matters.

   If you directly construct from these classes we've provided you with ``CompatBot`` and ``CompatAutoShardedBot``, which both inherit from ``CompatMixin``.
2. Modifying ``Bot.get_context()`` to return a context that inherits from ``InteractionAwareContext``. This is done automatically for you if you use the ``CompatMixin`` mixin.
3. If you use the ``application_commands.Range`` annotation helper for your commands, make sure you switch that to ``compat.Range``, or your normal text commands will fail to convert.

### Basic Usage
```py 
from discord.ext.compat import CompatBot, describe, inject

bot = CompatBot('$')

@bot.command()
@inject(guild_id=123456789)
@describe(x="The first number to add", y="The second number to add")
async def add(ctx, x: int, y: int):
    await ctx.send(f"{x} + {y} = {x + y}!")
    
bot.run('TOKEN')
```
