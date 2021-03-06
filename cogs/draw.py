import os
import re
import io
import urllib
import aiohttp
from typing import Optional

import numpy
from scipy.special import gamma  # noqa F401
import graphviz as gz
from matplotlib import pyplot as plt

import discord
from discord.ext import commands
from discord.utils import escape_markdown, escape_mentions

from core import basecog
from core.text import text
from core.config import config


class Draw(basecog.Basecog):
    """LaTeX and Graph drawing commands"""

    def __init__(self, bot):
        super().__init__(bot)
        self.rep_exp = {
            "x": "x",
            "sin": "numpy.sin",
            "cos": "numpy.cos",
            "tan": "numpy.tan",
            "tg": "numpy.tan",
            "arcsin": "numpy.arcsin",
            "arccos": "numpy.arccos",
            "arctan": "numpy.arctan",
            "arctg": "numpy.arctg",
            "sinh": "numpy.sinh",
            "cosh": "numpy.cosh",
            "tanh": "numpy.tanh",
            "tgh": "numpy.tgh",
            "arcsinh": "numpy.arcsinh",
            "arccosh": "numpy.arccosh",
            "arctanh": "numpy.arctanh",
            "arctgh": "numpy.arctgh",
            "exp": "numpy.exp",
            "log": "numpy.log10",
            "ln": "numpy.log",
            "sqrt": "numpy.sqrt",
            "cbrt": "numpy.cbrt",
            "abs": "numpy.absolute",
            "gamma": "gamma",
        }
        self.rep_op = {
            "+": " + ",
            "-": " - ",
            "*": " * ",
            "/": " / ",
            "//": " // ",
            "%": " % ",
            "^": " ** ",
        }

    def string2func(self, string):
        """ evaluates the string and returns a function of x """
        # surround operators with spaces and replace ^ with **
        for old, new in self.rep_op.items():
            string = string.replace(old, new)
        string = " ".join(string.split())

        # string = unidecode.unidecode(string)
        if not string.isascii():
            raise ValueError("Non ASCII characters are forbidden to use in math expression")

        # find all words and check if all are allowed:
        for word in re.findall("[a-zA-Z_]+", string):
            if word not in self.rep_exp.keys():
                raise ValueError('"{}" is forbidden to use in math expression'.format(word))

        for old, new in self.rep_exp.items():
            string = re.sub(rf"\b{old}\b", new, string)

        def func(x):
            return eval(string)  # nosec B307

        return func

    @commands.command(
        help=text.fill("draw", "latex_help", prefix=config.prefix),
        brief=text.get("draw", "latex_desc"),
        description=text.get("draw", "latex_desc"),
    )
    async def latex(self, ctx, *, equation):
        channel = ctx.channel
        async with ctx.typing():
            imgURL = (
                "http://www.sciweavers.org/tex2img.php?eq={}&bc=Black&fc=White&im=png&fs=18&ff=arev&edit=0"
            ).format(urllib.parse.quote(equation))
            async with aiohttp.ClientSession() as session:
                async with session.get(imgURL) as resp:
                    if resp.status != 200:
                        return await ctx.send("Could not get image.")
                    data = io.BytesIO(await resp.read())
                    await channel.send(file=discord.File(data, "latex.png"))

    @commands.command(
        help=text.fill("draw", "plot_help", prefix=config.prefix),
        brief=text.get("draw", "plot_desc"),
        description=text.get("draw", "plot_desc"),
    )
    async def plot(self, ctx, xmin: Optional[float] = -10, xmax: Optional[float] = 10, *, inp: str):

        equations = escape_mentions(escape_markdown(inp)).split(";")

        fig = plt.figure(dpi=300)
        ax = fig.add_subplot(1, 1, 1)

        if xmin < 0 < xmax:
            ax.spines["left"].set_position("zero")

        # Eliminate upper and right axes
        ax.spines["right"].set_color("none")
        ax.spines["top"].set_color("none")

        # Show ticks in the left and lower axes only
        ax.xaxis.set_tick_params(bottom=True, direction="inout")
        ax.yaxis.set_tick_params(left=True, direction="inout")

        successful_eq = 0
        msg = text.get("draw", "plot_err")
        numpy.seterr(divide="ignore", invalid="ignore")
        async with ctx.typing():
            for eq in equations:
                try:
                    func = self.string2func(eq)
                    x = numpy.linspace(xmin, xmax, 1000)
                    plt.plot(x, func(x))
                    plt.xlim(xmin, xmax)
                    successful_eq += 1
                except Exception as e:
                    msg += "\n" + eq + " - " + str(e)
            if msg != text.get("draw", "plot_err"):
                await ctx.send(msg)
            if successful_eq > 0:
                if not os.path.isdir("assets"):
                    os.mkdir("assets")
                plt.savefig("assets/plot.png", bbox_inches="tight", dpi=100)
                plt.clf()
                await ctx.send(file=discord.File("assets/plot.png"))
                os.remove("assets/plot.png")
        return

    @commands.command(
        name="digraph",
        aliases=("graphviz",),
        help=text.fill("draw", "digraph_help", prefix=config.prefix),
        brief=text.get("draw", "digraph_desc"),
        description=text.get("draw", "digraph_desc"),
    )
    async def digraph(self, ctx, *, equasion):
        """
        input equasion in dishraph format into graphviz
        save the file into assets/graphviz.png
        send the file to channel
        """
        src = gz.Source(equasion, format="png")
        if not os.path.isdir("assets"):
            os.mkdir("assets")
        src.render("assets/graphviz", view=False)

        await ctx.send(file=discord.File("assets/graphviz.png"))
        os.remove("assets/graphviz")
        os.remove("assets/graphviz.png")

    @classmethod
    def is_graphviz_message(self, body):
        return body.startswith("```digraph") and body.endswith("```") and body.count("\n") >= 2

    @commands.Cog.listener()
    async def on_message(self, message):
        """
        if message is disgraph compatible
        add the execution (play) button
        """
        if not self.is_graphviz_message(message.content):
            return

        if message.author.bot:
            return

        await message.add_reaction("▶")

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        """
        check if users clicked the play button on executable code
        the bot has to be a reactor on the executable message
        """

        message = reaction.message
        if not self.is_graphviz_message(message.content):
            return

        if message.author.bot or user.bot or message.author != user:
            return

        if str(reaction.emoji) != "▶":
            return

        if self.bot.user not in await reaction.users().flatten():
            return

        ctx = commands.Context(
            prefix=self.bot.command_prefix,
            guild=message.guild,
            channel=message.channel,
            message=message,
            author=user,
        )
        await self.digraph.callback(
            self,
            ctx,
            equasion=message.content.strip("` ` `").replace("digraph\n", "", 1),
        )

        await ctx.message.remove_reaction("▶", ctx.author)
        await ctx.message.remove_reaction("▶", self.bot.user)


def setup(bot):
    bot.add_cog(Draw(bot))
