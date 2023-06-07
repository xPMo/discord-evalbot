#!/usr/bin/python
import discord
import logging
import os
import re
from subprocess import run, PIPE, TimeoutExpired

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

## Bot

INLINE_PAT = re.compile(r'([^`\\]|\\.)*`([^`]*)`', re.S)

try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    logging.WARNING('Could not load dotenv')
token = os.environ.get('BOT_TOKEN')
intents = discord.Intents.default()
bot = discord.Bot()

CHECKMAP = {
    'zsh': {
        'command': ['zsh', '-f'],
        'container': 'eval-shell:alpine'
    }
}
for shell in ['bash', 'sh', 'dash', 'ksh']:
    CHECKMAP[shell] = {
        'command': [f'--shell={shell}', '/dev/stdin'],
        'container': 'koalaman/shellcheck',
        'workdir': '/',
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

def parseblock(s: str):
    lines = s.split('\n')
    lang = 'bash'
    while line := lines.pop(0):
        if line.startswith('```'):
            lang = line.removeprefix('```').strip() or lang
            break
    else:
        # No line began with code fence, try single-backtick block
        if match := INLINE_PAT.match(s):
            return match.groups()[1], lang
        else:
            return s, lang
    code = []
    # assume if loop finishes that the fence was just missing from the end
    while line := lines.pop(0):
        if line.startswith('```'):
            break
        code.append(line)
    return '\n'.join(code), lang

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
            parts += [f'```{lang.get("stdout-class")}\n', stdout.decode().strip('\n'), '\n```']
        else:
            parts.append('*no stdout*')
        if stderr:
            parts += [f'```{lang.get("stderr-class")}\n', stderr.decode().strip('\n'), '\n```']
        else:
            parts.append('*no stderr*')

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
        return await interaction.edit_original_response(content=run_code(langmap, code, message.author))
    except Exception as e:
        return await ctx.respond('Failed:\n```\n{e.message}\n```')

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

bot.run(token)
