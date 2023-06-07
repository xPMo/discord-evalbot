#!/usr/bin/python
import discord
import logging
import os
import re
import requests
from html2text import html2text

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

## Bot

INLINE_PAT = re.compile(r'([^`\\]|\\.)*`([^`]*)`', re.S)

token = os.environ.get('DISCORD_BOT_TOKEN')
intents = discord.Intents.default()
bot = discord.Bot()

CHECKMAP = {
    'zsh': {
        'command': ['zsh', '-f'],
        'container': 'alpine-eval-shell'
    }
}
for shell in ['bash', 'sh', 'dash', 'ksh']:
    CHECKMAP[shell] = {
        'command': [f'--shell={shell}', '/dev/stdin'],
        'container': 'koalaman/shellcheck',
        'workdir': '/',
    }


LANGMAP = {
    'bash': {
        'command': ['bash', '-O', 'extglob', '-O', 'globstar'],
        'container': 'alpine-eval-shell',
    },
    'zsh': {
        'command':  ['zsh', '-l', '--extendedglob', '--multibyte'],
        'podman_opts': ['--env', 'LANG=C.UTF-8'],
        'container': 'alpine-eval-shell',
    }
}

def parseblock(s: str):
    lines = s.split('\n')
    lang = 'bash'
    while line := lines.pop():
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
    while line := lines.pop():
        if line.startswith('```'):
            break
        code.append(line)
    return code.join('\n'), lang

def run_code(self, lang, code, label):
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
            parts.append(f'**Process exited non-zero: `{proc.returncode}`**')
    except TimeoutExpired as e:
        stdout = e.stdout
        stderr = e.stderr
        parts.append((
            f'**Process timed out in {timeout}**',
            f'Process timed out in {timeout}s'
        ))

    stdout = stdout and self.code_block(lang.get('stdout-class'), stdout.decode().strip('\n'))
    stderr = stderr and self.code_block(lang.get('stderr-class'), stderr.decode().strip('\n'))
    if not stdout and not stderr:
        parts.append('*no stdout or stderr*')
    else:
        parts += [stdout or '*no stdout*', stderr or '*no stderr*']

    return '\n'.join(parts)

@bot.event
async def on_ready():
    logging.info(f'We have logged in as {bot.user}')

@bot.message_command(name='Shellcheck')
async def eval_entry(ctx, message):
    try:
        code, lang = parseblock(message.content)
        langmap = CHECKMAP.get(lang)
        if not langmap:
            return ctx.send(f'No matching language for {lang}~')
        ctx.send(f'Code:\n```\n{code}\n```Lang: {lang}')
    except Exception(e):
        return await ctx.respond('Failed:\n```\n{e}\n```')

@bot.message_command(name='Evaluate Code')
async def eval_entry(ctx, message):
    try:
        code, lang = parseblock(message.content)
        langmap = LANGMAP.get(lang)
        if not langmap:
            return ctx.send(f'No matching language for {lang}~')
        ctx.send(f'Code:\n```\n{code}\n```Lang: {lang}')
    except Exception(e):
        return await ctx.respond('Failed:\n```\n{e}\n```')

bot.run(token)
