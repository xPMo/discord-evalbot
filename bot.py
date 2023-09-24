#!/usr/bin/python
import discord
import logging
import os
import re
import signal
from subprocess import run, PIPE, TimeoutExpired

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

## Bot



try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    logging.warning('Could not load dotenv')
token = os.environ.get('BOT_TOKEN')
intents = discord.Intents.default()
bot = discord.Bot()

RETCODEMAP = dict()
for sig in signal.valid_signals():
    try:
        RETCODEMAP[sig.value + 128] = sig.name
    except:
        pass

FMTMAP = dict()
# shfmt language dialect translation
fmtmap = {'ksh': 'mksh', 'sh': 'posix'}

CHECKMAP = dict()

for shell in ['bash', 'sh', 'dash', 'ksh']:
    CHECKMAP[shell] = {
        'command': [f'--shell={shell}', '--color=always', '/dev/stdin'],
        'container': 'koalaman/shellcheck',
        'workdir': '/',
    }
    FMTMAP[shell] = {
        'command': [f'-ln={fmtmap.get(shell) or shell}', '-bn', '-s'],
        'container': 'mvdan/shfmt:latest-alpine',
        'stdout-class': shell
    }

LANGMAP = {
    'sh': {
        'command': ['sh'],
        'container': 'eval-shell:alpine',
    },
    'bash': {
        'command': ['bash', '-O', 'extglob', '-O', 'globstar'],
        'container': 'eval-shell:alpine',
    },
    'zsh': {
        'command':  ['zsh', '-l', '--extendedglob', '--multibyte'],
        'podman_opts': ['--env', 'LANG=C.UTF-8'],
        'container': 'eval-shell:alpine',
    }
}
for m in [LANGMAP, CHECKMAP, FMTMAP]:
    m['shell'] = m.get('bash')
    m['mksh']  = m.get('ksh')

INLINE_PAT = re.compile(r'([^`\\]|\\.)*`([^`]*)`', re.S)
LANG_PAT   = re.compile(r'^([a-zA-Z]*)\n', re.S)

def parseblock(s: str):
    lang = 'bash'
    try:
        before, code, after = s.split('```', maxsplit=2)
        if match := LANG_PAT.match(code):
            lang = match.groups()[0].lower() or lang
            code = code[slice(1 + len(match.groups()[0]), -1)]
        logging.info(f'Code block: {lang}: {repr(code)}')
        return code, lang
    except ValueError:
        # No line began with code fence, try single-backtick block
        if match := INLINE_PAT.match(s):
            return match.groups()[1], lang
        return s, lang

def run_code(lang, code, label):
    container = lang['container']
    podman_cmd = lang['command']
    logging.info(f"Running in podman {container} with {podman_cmd}")
    podman_opts = [f'--label={label}']

    # set limits
    timeout = lang.get('timeout') or 5
    net = lang.get('net') or 'none'
    pids = lang.get('pids-limit') or 64
    mem = lang.get('memory') or '32M'
    workdir = lang.get('workdir') or '/root'

    podman_opts += [f'--pids-limit={pids}', f'--memory={mem}', f'--net={net}', f'--workdir={workdir}']
    podman_opts += lang.get('podman_opts') or []

    parts = []
    try:
        proc = run(['podman', 'run', '--rm', '-i'] + podman_opts + [container] + podman_cmd,
            input=code.encode('utf-8'), capture_output=True, timeout=timeout)
        stdout = proc.stdout
        stderr = proc.stderr
        if proc.returncode != 0:
            try:
                parts.append(f'**Process exited non-zero: `{proc.returncode}` `{RETCODEMAP[proc.returncode]}`**\n')
            except KeyError:
                parts.append(f'**Process exited non-zero: `{proc.returncode}`**\n')
    except TimeoutExpired as e:
        stdout = e.stdout
        stderr = e.stderr
        parts.append(
            f'**Process timed out in {timeout}s**\n'
        )

    if not stdout and not stderr:
        parts.append('*no stdout or stderr*')
    else:
        if stdout:
            parts += [f'```{lang.get("stdout-class") or "ansi"}\n', stdout.decode().strip('\n'), '\n```']
        else:
            parts.append('*no stdout*')
        if stderr:
            parts += [f'```{lang.get("stderr-class") or "ansi"}\n', stderr.decode().strip('\n'), '\n```']

    return ''.join(parts)

@bot.event
async def on_ready():
    logging.info(f'We have logged in as {bot.user}')

@bot.message_command(name='Shellcheck')
async def check_command(ctx, message):
    try:
        code, lang = parseblock(message.content)
        langmap = CHECKMAP.get(lang)
        if not langmap:
            return await ctx.respond(f'No matching language for {lang}!')
        interaction = await ctx.respond('Checking...')
        content = run_code(langmap, code, message.author)
        splits = content.rsplit('\n\n', 1)
        if len(splits) == 2:
            content = splits[0] + '```' + splits[1].removesuffix('```')
        return await interaction.edit_original_response(content=content)
    except Exception as e:
        return await ctx.respond(f'Failed:\n```\n{e.message}\n```')

@bot.message_command(name='Evaluate Code')
async def eval_command(ctx, message):
    try:
        code, lang = parseblock(message.content)
        langmap = LANGMAP.get(lang)
        if not langmap:
            return await ctx.respond(f'No matching language for {lang}!')
        interaction = await ctx.respond('Running...')
        return await interaction.edit_original_response(content=run_code(langmap, code, message.author))
    except Exception as e:
        await ctx.respond(f'Failed:\n```\n{e}\n```')
        raise e

@bot.slash_command(name='eval', description='Evaluate Code')
async def eval_slash(
    ctx: discord.ApplicationContext,
    code: discord.Option(str, 'snippet to run', name='snippet'),
    lang: discord.Option(str, 'language choice', name='language', choices=list(LANGMAP.keys()), default='bash'),
):
    try:
        langmap = LANGMAP.get(lang)
        if not langmap:
            return await ctx.respond(f'No matching language for {lang}!')
        interaction = await ctx.respond('Running...')
        return await interaction.edit_original_response(content=run_code(langmap, code, ctx.author))
    except Exception as e:
        await ctx.respond(f'Failed:\n```\n{e}\n```')
        raise e
    
    

@bot.message_command(name='Format Code')
async def fmt_command(ctx, message):
    try:
        code, lang = parseblock(message.content)
        langmap = FMTMAP.get(lang)
        if not langmap:
            return await ctx.respond(f'No matching language for {lang}!')
        interaction = await ctx.respond('Formatting...')
        return await interaction.edit_original_response(content=run_code(langmap, code, message.author))
    except Exception as e:
        await ctx.respond(f'Failed:\n```\n{e}\n```')
        raise e

bot.run(token)
