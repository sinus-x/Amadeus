import re
import asyncio
from datetime import datetime
from datetime import timedelta
from dateparser.search import search_dates

import discord
from discord import CategoryChannel
from discord.ext import tasks, commands

from core import basecog
from core.text import text
from core.config import config
from repository import unverify_repo


repository = unverify_repo.UnverifyRepository()


class Unverify(basecog.Basecog):
    """Voting based commands"""

    def __init__(self, bot):
        self.bot = bot
        self.unverify_loop.start()

    def cog_unload(self):
        self.unverify_loop.cancel()

    @tasks.loop(seconds=10.0)
    async def unverify_loop(self):
        repo = repository.get_waiting()
        if repo != []:
            for row in repo:
                duration = row.end_time - datetime.now()
                duration_in_s = duration.total_seconds()
                if row.end_time < datetime.now():
                    await self.reverify_user(row)
                elif duration_in_s < 10:
                    await self.reverify_user(row, time=duration_in_s)
        repo = repository.get_finished()
        if repo != []:
            for row in repo:
                if row.end_time < (datetime.now() - timedelta(days=7)):
                    await self.log(
                        level="debug",
                        message=f"Deleting unverify from db: ID: {row.idx}, time: {row.end_time}, status: {row.status}, \nmessage: {row.reason}",
                    )
                    repository.delete(row.idx)

    @unverify_loop.before_loop
    async def before_unverify_loop(self):
        if not self.bot.is_ready():
            await self.log(level="info", message="Unverify loop - waiting until ready()")
            await self.bot.wait_until_ready()

    async def parse_datetime(self, arg):
        dates = search_dates(
            arg.replace(".", "-"),
            languages=["en"],
            settings={"PREFER_DATES_FROM": "future", "PREFER_DAY_OF_MONTH": "first", "DATE_ORDER": "DMY"},
        )
        if dates is None:
            return None, ""

        weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

        for day in weekdays:
            if str("next " + day) in arg.lower() and day in dates[0][0].lower():
                date = dates[0][1] + timedelta(days=7)
                break
        else:
            date = dates[0][1]

        if date < datetime.now():
            date = date.replace(day=(datetime.now().day))
            if date < datetime.now():
                date = date + timedelta(days=1)

        x = re.search(r"([0-9]|0[0-9]|1[0-9]|2[0-3]):[0-5][0-9]", dates[0][0])
        if x is None:
            date = date.replace(hour=9, minute=0, second=0)

        date_str = dates[0][0]

        return date, date_str

    async def reverify_user(self, row, time=None):
        guild = self.bot.get_guild(row.guild_id)
        member = guild.get_member(row.user_id)
        if member is None:
            return

        if time is not None:
            await asyncio.sleep(time)
        await self.log(level="info", message=f"Reverifying {member.name}")
        roles = []
        for role_id in row.roles_to_return:
            role = discord.utils.get(guild.roles, id=role_id)
            roles.append(role)
        try:
            await member.add_roles(*roles, reason=None, atomic=True)
        except discord.errors.Forbidden:
            pass
        for channel_id in row.channels_to_return:
            channel = discord.utils.get(guild.channels, id=channel_id)
            user_overw = channel.overwrites_for(member)
            user_overw.update(read_messages=True)
            await channel.set_permissions(member, overwrite=user_overw, reason="Unverify")

        for channel_id in row.channels_to_remove:
            channel = discord.utils.get(guild.channels, id=channel_id)
            user_overw = channel.overwrites_for(member)
            user_overw.update(read_messages=False)
            await channel.set_permissions(member, overwrite=user_overw, reason="Unverify")

        for id in config.roles_unverify:
            role = discord.utils.get(guild.roles, id=id)
            if role is not None:
                unverify_role = role
                try:
                    await member.remove_roles(unverify_role, reason="Reverify", atomic=True)
                except discord.errors.Forbidden:
                    pass
                break
            else:
                return None

        await member.send(f"Byly ti vráceny práva na serveru {guild.name}.")
        repository.set_finished(row.idx)

    async def unverify_user(
        self,
        ctx: commands.Context,
        member: discord.abc.User,
        lines: str,
        date: datetime,
        func: str,
        args: str = "",
    ):
        roles_to_keep = []
        roles_to_remove = []
        channels_to_keep = []
        removed_channels = []

        for id in config.roles_unverify:
            role = discord.utils.get(ctx.guild.roles, id=id)
            if role is not None:
                unverify_role = role
                break
            else:
                return None

        for value in args:
            role = discord.utils.get(ctx.guild.roles, name=value)
            channel = discord.utils.get(ctx.guild.channels, name=value)
            if role is not None and role in member.roles:
                roles_to_keep.append(role)
            elif channel is not None:
                perms = channel.permissions_for(member)

                if not perms.read_messages:
                    continue
                channels_to_keep.append(channel)

        for role in member.roles:
            if role not in roles_to_keep and role.position != 0:
                roles_to_remove.append(role)
        try:
            await member.remove_roles(*roles_to_remove, reason=func, atomic=True)
        except discord.errors.Forbidden:
            pass
        await member.add_roles(unverify_role, reason=func, atomic=True)
        await asyncio.sleep(2)

        for channel in member.guild.channels:
            if not isinstance(channel, CategoryChannel):
                perms = channel.permissions_for(member)
                user_overw = channel.overwrites_for(member)

                if channel in channels_to_keep:
                    if not perms.read_messages:
                        user_overw.update(read_messages=True)
                        await channel.set_permissions(member, overwrite=user_overw, reason=func)
                elif perms.read_messages and not user_overw.read_messages:
                    pass
                elif not perms.read_messages:
                    pass
                else:
                    user_overw.update(read_messages=False)
                    await channel.set_permissions(member, overwrite=user_overw, reason=func)
                    removed_channels.append(channel.id)

        removed_roles = [role.id for role in roles_to_remove]
        added_channels = [channel.id for channel in channels_to_keep]

        lines = "\n".join(lines)
        if len(lines) > 1024:
            lines = lines[:1024]
            lines = lines[:-3] + "```" if lines.count("```") % 2 != 0 else lines

        result = repository.add(
            guild_id=member.guild.id,
            user_id=member.id,
            start_time=datetime.now(),
            end_time=date,
            roles_to_return=removed_roles,
            channels_to_return=removed_channels,
            channels_to_remove=added_channels,
            reason=lines,
        )
        return result

    @commands.cooldown(rate=5, per=20.0, type=commands.BucketType.user)
    @commands.command(
        brief=text.get("unverify", "selfunverify desc"),  # TODO fix
        description=text.get("unverify", "selfunverify desc"),  # TODO fix
        help=text.fill("unverify", "selfunverify help", prefix=config.prefix),  # TODO fix
    )
    async def selfunverify(self, ctx):
        message = ctx.message
        lines = message.content.split("\n")
        arg = lines.pop(0)
        arg = arg.replace("weekend", "saturday")
        date, date_str = await self.parse_datetime(arg)
        printdate = date.strftime("%d.%m.%Y %H:%M:%S")
        member = ctx.message.author
        await self.log(level="info", message=f"Selfunverify: Member - {member.name}, Until - {date}")

        if date is None:
            if len(lines) == 0:
                await ctx.send(">>> " + text.fill("unverify", "selfunverify help", prefix=config.prefix))
                return
            await ctx.send(text.get("unverify", "datetime not found"))
            date = datetime.now() + timedelta(days=1)

        for prefix in config.prefixes:
            if arg[0] == prefix:
                arg = arg.replace(f"{prefix}selfunverify ", "")

        arg = arg.replace(date_str, "")
        args = re.split("[;, \n]", arg)
        while "" in args:
            args.remove("")

        result = await self.unverify_user(
            ctx, member=member, args=args, lines=lines, date=date, func="Self unverify"
        )

        if result is not None:
            await self.log(
                level="debug", message=f"Selfunverify success: Member - {member.name}, Until - {date}"
            )

        await member.send(
            f"Byly ti dočasně odebrány všechny práva na serveru {ctx.guild.name}. Přístup ti bude navrácen {printdate}. Důvod: Self unverify"
        )


def setup(bot):
    bot.add_cog(Unverify(bot))
