from __future__ import annotations

import functools
import os
from collections import defaultdict
from typing import Any, Callable, Container, Dict, Iterable, List, Optional, TYPE_CHECKING, Type, TypeVar, Union
from warnings import warn

import discord
from discord.application_commands import (
    ApplicationCommand,
    ApplicationCommandMeta,
    ApplicationCommandTree,
    Range as _Range,
    _get_namespaces,
    _resolve_option_annotation,
    option,
)
from discord.ext import commands
from discord.utils import MISSING

if TYPE_CHECKING:
    from discord.application_commands import (
        ApplicationCommandOptionTypeT,
        ApplicationCommandOptionChoiceT,
    )

    CommandDecorator = Callable[[Union[commands.Command, Callable[..., Any]]], Union[commands.Command, Callable[..., Any]]]

    BotT = TypeVar('BotT', bound=Union[commands.Bot, commands.AutoShardedBot], covariant=True)
    ContextT = TypeVar('ContextT', bound=commands.Context, covariant=True)
    MakeshiftMessageT = TypeVar('MakeshiftMessageT', bound='MakeshiftMessage')

__all__ = (
    'CompatAutoShardedBot',
    'CompatBot',
    'CompatBotMixin',
    'InteractionAwareContext',
    'MakeshiftMessage',
    'Range',
    'describe',
    'inject',
    'override_option',
)


class Injector:
    def __init__(self, bot: BotT, *, tree: ApplicationCommandTree = MISSING) -> None:
        self.bot: BotT = bot
        self.tree: ApplicationCommandTree = tree or ApplicationCommandTree('discord-ext-compat-injector')

    def inject(
        self,
        name: str = MISSING,
        *,
        type: discord.ApplicationCommandType = discord.ApplicationCommandType.chat_input,
        description: str = MISSING,
        parent: ApplicationCommandMeta = MISSING,
        default_permission: bool = True,
        option_kwargs: Dict[str, Any] = MISSING,
        guild_id: int = MISSING,
        tree: ApplicationCommandTree = MISSING,
        excluded_options: Container[str] = (),
    ) -> CommandDecorator:
        def decorator(func: Union[commands.Command, Callable[..., Any]]) -> Union[commands.Command, Callable[..., Any]]:
            nonlocal name, description, parent

            if not isinstance(func, commands.Command):
                func.__compat_inject__ = functools.partial(
                    self.inject,
                    name=name,
                    type=type,
                    description=description,
                    parent=parent,
                    default_permission=default_permission,
                    option_kwargs=option_kwargs,
                    guild_id=guild_id,
                    tree=tree
                )
                return func

            command: commands.Command = func
            func = command.callback

            if name is MISSING:
                name = command.name

            if description is MISSING and command.short_doc:
                description = command.short_doc[:100]  # TODO: maybe allow user to explicitly handle this?

            if parent is MISSING and command.parent and hasattr(command.parent, '__compat_application_command__'):
                parent = command.parent.__compat_application_command__

            if not description:
                raise ValueError(f'tried to convert {func.__name__!r} into an application command, but it has no description')

            if not hasattr(func, '__compat_application_command_options__'):
                func.__compat_application_command_options__ = defaultdict(lambda: option(description=MISSING))

            # noinspection PyShadowingNames
            # we don't actually "use" the shadowed identifier so I don't mind doing this
            annotations = func.__annotations__
            options = func.__compat_application_command_options__

            local_ns, global_ns = _get_namespaces({'__module__': func.__module__})

            for key, parameter in command.clean_params.items():
                if key in excluded_options:
                    continue

                default = parameter.default
                current = options[key]

                if default is parameter.empty:
                    current.required = True
                    continue

                current.required = False
                current.default = default

                if annotation := annotations.get(key):
                    try:
                        _resolve_option_annotation(current, annotation, args=(global_ns, local_ns, {}))
                    except TypeError:
                        current.type = discord.ApplicationCommandOptionType.string

            @functools.wraps(func)
            async def callback(attrs: ApplicationCommand, interaction: discord.Interaction) -> None:
                kwargs = {k: getattr(attrs, k) for k in command.clean_params if k not in excluded_options}
                message = MakeshiftMessage.from_interaction(interaction=interaction, channel=interaction.channel)  # type: ignore
                message.content = '/' + command.qualified_name

                bot: BotT = interaction.client  # type: ignore
                ctx = await bot.get_context(message)
                if ctx is None or ctx.command is None:
                    return

                bot.dispatch("command", ctx)
                try:
                    if await bot.can_run(ctx, call_once=True):
                        if not command.cog:
                            await func(ctx, **kwargs)
                        else:
                            await func(command.cog, ctx, **kwargs)  # type: ignore
                    else:
                        raise commands.CheckFailure("The global check once functions failed.")
                except commands.CommandError as exc:
                    await ctx.command.dispatch_error(ctx, exc)
                else:
                    bot.dispatch("command_completion", ctx)

            func.__compat_application_command__ = application_command = ApplicationCommandMeta(
                os.urandom(16).hex(),
                (ApplicationCommand,),
                {
                    '__module__': func.__module__,
                    '__doc__': func.__doc__,
                    '__annotations__': annotations,
                    '__qualname__': func.__qualname__,
                    'callback': callback,
                    **options,
                },
                type=type,
                name=name,
                description=description,
                parent=parent,
                default_permission=default_permission,
                option_kwargs=option_kwargs,
                guild_id=guild_id,
                tree=tree or self.tree,
            )

            self.bot.add_application_command(application_command, guild_id=guild_id)
            return command

        return decorator


def override_option(
    param_name: str,
    *,
    type: ApplicationCommandOptionTypeT = MISSING,
    name: str = MISSING,
    description: str = MISSING,
    required: bool = MISSING,
    optional: bool = MISSING,
    choices: ApplicationCommandOptionChoiceT = MISSING,
    channel_types: Iterable[discord.ChannelType] = MISSING,
    min_value: float = MISSING,
    max_value: float = MISSING,
    default: Any = None,
) -> CommandDecorator:
    """Overrides the data for previously inferred application command option data.

    All parameters except for ``param_name`` are keyword-only and optional.

    .. note::
        When used as a decorator, decorate this **below** the :func:`@inject <inject>` decorator.

    Parameters
    ----------
    param_name: str
        This parameter is required - the **parameter name** that contains the option of override.

        This should be the name of the parameter and not the name of the option - although in most cases they will be the same.
    type: Union[:class:`~.ApplicationCommandType`, :class:`type`]
        The type of this option. Defaults to the annotation given with this option, or ``str``.
    name: str
        The name of this option.
    description: str
        The description of this option. Required.
    required: bool
        Whether or not this option is required. Defaults to ``False``.
    optional: bool
        An inverted alias for ``required``. This cannot be used with ``required``, and vice-versa.
    choices
        If specified, only the choices given will be available to be selected by the user.

        Argument should either be a mapping of choice names to their return values,
        A sequence of the possible choices, or a sequence of :class:`.ApplicationCommandOptionChoice`.
    channel_types: Iterable[:class:`ChannelType`]
        An iterable of all the channel types this option will take.
        Defaults to taking all channel types.

        Only applicable for ``channel`` types.
    min_value: Union[:class:`int`, :class:`float`]
        The minimum numerical value that this option can have.
        Defaults to no minimum value.

        Only applicable for ``integer`` or ``number`` types.
    max_value: Union[:class:`int`, :class:`float`]
        The maximum numerical value that this option can have. Must greater than or equal to ``min_value`` if it is provided.
        Defaults to no maximum value.

        Only applicable for ``integer`` or ``number`` types.
    default
        The default value passed to the attribute if the option is not passed.
        Defaults to ``None``.
    """
    def decorator(func: Union[commands.Command, Callable[..., Any]]) -> Union[commands.Command, Callable[..., Any]]:
        original = func
        if isinstance(func, commands.Command):
            func = func.callback

        if not hasattr(func, '__compat_application_command_options__'):
            func.__compat_application_command_options__ = defaultdict(lambda: option(description=MISSING))

        current = func.__compat_application_command_options__[param_name]

        kwargs = dict(
            type=type,
            name=name,
            description=description,
            required=required,
            optional=optional,
            choices=choices,
            channel_types=channel_types,
            min_value=min_value,
            max_value=max_value,
            default=default,
        )
        new = option(**kwargs)

        for key, value in kwargs.items():
            if value is MISSING:
                continue

            setattr(current, key, getattr(new, key))

        return original

    return decorator


def describe(param_name: str, description: str) -> CommandDecorator:
    """A shortcut for :func:`override_option` which adds a description to an option.

    This abstraction was made as the commands framework did not provide a programmatic way to add descriptions to options out of the box.

    .. note::
        When used as a decorator, decorate this **below** the :func:`@inject <inject>` decorator.
    """
    return override_option(param_name, description=description)


def inject(
    name: str = MISSING,
    *,
    type: discord.ApplicationCommandType = discord.ApplicationCommandType.chat_input,
    description: str = MISSING,
    parent: ApplicationCommandMeta = MISSING,
    default_permission: bool = True,
    option_kwargs: Dict[str, Any] = MISSING,
    guild_id: int = MISSING,
    tree: ApplicationCommandTree = MISSING,
    excluded_options: Container[str] = (),
) -> CommandDecorator:
    """A decorator which declares an application command out of the given function/command.

    All parameters are optional, and all except for ``name`` are keyword-only.

    Parameters
    ----------
    name: :class:`str`
        The name of the application command. Defaults to the name of the command.
    type: :class:`discord.ApplicationCommandType`
        The application command type. Defaults to :attr:`discord.ApplicationCommandType.chat_input`.

        .. note::
            This module has only been tested on chat input commands. Other types may be unstable.
    description: :class:`str`
        The description of the application command. Defaults to the ``short_doc`` of the command.
    parent: Type[:class:`discord.application_commands.ApplicationCommand`]
        The parent command of the application command.
    default_permission: bool
        Whether or not this command will be enabled by default when added to a guild.
        Defaults to ``True``.
    option_kwargs: Dict[str, Any]
        Default kwargs to pass in for each application command option.
    guild_id: int
        The ID of the guild that this application command will automatically be added to.
        Leave blank to make this a global command.
    tree: :class:`.ApplicationCommandTree`
        The command tree this command will be added to.
    excluded_options: Container[:class:`str`]
        A list of parameter names which represents the parameters that will be ignored when trying to convert them to options.

    Example
    -------

    .. code:: python3

        @bot.command()
        @inject(guild_id=123456789)
        @describe("a", "The first number")
        @describe("b", "The second number")

        async def add(ctx: commands.Context, a: int, b: int):
            \"""Adds two numbers together\"""
            await ctx.send(f"{a} + {b} = {a + b}")
    """
    def decorator(func: Union[commands.Command, Callable[..., Any]]) -> Union[commands.Command, Callable[..., Any]]:
        kwargs = dict(
            name=name,
            type=type,
            description=description,
            parent=parent,
            default_permission=default_permission,
            option_kwargs=option_kwargs,
            guild_id=guild_id,
            tree=tree,
            excluded_options=excluded_options,
        )

        if isinstance(func, commands.Command):
            if injector := getattr(func, '__compat_injector__', None):
                injector.inject(**kwargs)(func)

            return func

        func.__compat_injection_kwargs__ = kwargs
        return func

    return decorator


class CompatBotMixin:
    if TYPE_CHECKING:
        _injector: Injector

    def __init__(self, *args, **options):
        self: BotT
        self._injector = Injector(self)

        super().__init__(*args, **options)

    def add_command(self, command: commands.Command) -> None:
        if hasattr(command.callback, '__compat_inject__'):
            command.callback.__compat_inject__()(command)

        elif kwargs := getattr(command.callback, '__compat_injection_kwargs__', None):
            self._injector.inject(**kwargs)(command)

        command.__compat_injector__ = self._injector
        super().add_command(command)  # type: ignore

    async def get_prefix(self, message: discord.Message) -> Union[str, List[str]]:
        if isinstance(message, MakeshiftMessage):
            return '/'

        return await super().get_prefix(message)  # type: ignore

    async def get_context(self, message: discord.Message, *, cls: Type[InteractionAwareContext] = MISSING) -> commands.Context:
        if cls is not MISSING and not issubclass(cls, InteractionAwareContext):
            warn(
                'the supplied cls parameter is not a subclass of InteractionAwareContext, '
                'which may not be compatible with discord-ext-compat.'
            )

        return await super().get_context(message, cls=cls or InteractionAwareContext)  # type: ignore


class CompatBot(CompatBotMixin, commands.Bot):
    ...


class CompatAutoShardedBot(CompatBotMixin, commands.AutoShardedBot):
    ...


class MakeshiftMessage(discord.PartialMessage):
    author: Union[discord.User, discord.Member]
    activity = application = edited_at = reference = webhook_id = None
    attachments = components = reactions = stickers = []  # TODO: maybe not default this to a mutable object
    content: str
    tts: bool = False

    raw_mentions = discord.Message.raw_mentions
    clean_content = discord.Message.clean_content
    channel_mentions = discord.Message.channel_mentions
    raw_role_mentions = discord.Message.raw_role_mentions
    raw_channel_mentions = discord.Message.raw_channel_mentions

    _interaction: discord.Interaction

    @classmethod
    def from_interaction(
        cls: Type[MakeshiftMessageT],
        interaction: discord.Interaction,
        channel: discord.abc.Messageable,
    ) -> MakeshiftMessageT:
        message = cls(channel=channel, id=interaction.id)
        message.author = interaction.user
        message._interaction = interaction

        return message

    async def edit(self, **kwargs: Any) -> None:
        response: discord.InteractionResponse = self._interaction.response  # type: ignore
        if response.is_done():
            await self._interaction.edit_original_message(**kwargs)
            return

        await response.edit_message(**kwargs)


class InteractionAwareContext(commands.Context):
    if TYPE_CHECKING:
        message: Union[discord.Message, MakeshiftMessage]
        interaction: Optional[discord.Interaction]

    def __init__(self, **options):
        super().__init__(**options)

        self.interaction = self.message._interaction if isinstance(self.message, MakeshiftMessage) else None

    def is_interaction(self) -> bool:
        """:class:`bool`: Whether or not an interaction is attached to this context."""
        return self.interaction is not None

    async def send(self, content: Optional[str] = None, **kwargs) -> Optional[discord.Message]:
        if self.is_interaction():
            for key in ('reference', 'mention_after', 'delete_after', 'nonce'):
                kwargs.pop(key, None)

            if self.interaction.response.is_done():
                await self.interaction.followup.send(content, **kwargs)
            else:
                await self.interaction.response.send_message(content, **kwargs)
            return

        kwargs.pop('ephemeral', None)
        return await super().send(content=content, **kwargs)

    async def defer(self, *, loading: bool = False, ephemeral: bool = False) -> None:
        """|coro|

        Defers the interaction response if there is an interaction in this context.
        If not, this will do nothing.

        This is typically used when the interaction is acknowledged
        and a secondary action will be done later.

        Parameters
        -----------
        loading: :class:`bool`
            Whether the user should see a loading state.

            .. note::

                You must use the ``ephemeral`` kwarg to send ephemeral followups
                when this is set to ``True``.

        ephemeral: :class:`bool`
            Indicates whether the deferred message will eventually be ephemeral.
            This only applies if ``loading`` is set to ``True`` or for interactions
            of type :attr:`InteractionType.application_command`.

        Raises
        -------
        HTTPException
            Deferring the interaction failed.
        InteractionResponded
            This interaction has already been responded to before.
        """
        if self.is_interaction():
            self.interaction.response.defer(loading=loading, ephemeral=ephemeral)

    async def reply(self, content: Optional[str] = None, **kwargs) -> discord.Message:
        func = self.send if self.is_interaction() else self.reply
        return await func(content=content, **kwargs)


class Range(_Range, commands.Converter[Union[int, float]]):
    async def convert(self, ctx: ContextT, argument: str) -> Union[int, float]:
        try:
            argument = int(argument)
        except ValueError:
            pass
        else:
            if self.min_value <= argument <= self.max_value:
                return argument

        raise commands.BadArgument(
            f'Expected a number between {self.min_value} and {self.max_value}, but got {argument!r} instead'
        )


def monkeypatch():
    """Monkeypatches and directly modifies Discord models to make them compatible with this library.

    Note that this is not recommended as it is at the end of the day, monkeypatching.

    If you don't exactly know what :link:`monkeypatching is <https://en.wikipedia.org/wiki/Monkey_patch>`, then you probably shouldn't use this module.
    """
    discord.application_commands.Range = Range
    commands.Bot = CompatBot
    commands.AutoShardedBot = CompatAutoShardedBot
    commands.Context = InteractionAwareContext
