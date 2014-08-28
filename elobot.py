#!/usr/bin/env python

from __future__ import print_function

from twisted.internet import reactor, protocol
from twisted.words.protocols import irc
import json
from datetime import date


state = {
    'next_id': 0,
    'players': {},
    'pending': [],
    'archived': [],
}

state_file = 'ladder.json'
initial_rating = 1200
cmd_prefix = '.'


def save():
    with open(state_file, 'w') as f:
        json.dump(state, f, indent=2)


def load():
    with open(state_file, 'r') as f:
        global state
        state = json.load(f)


def register(bot, user, chan, args):
    player = user.split('!')[0]
    if player in state['players']:
        bot.say(chan, 'Already registered!')
        return

    state['players'][player] = {
        'rating': initial_rating,
        'joined': '%s' % date.today(),
        'games': 0,
        'wins': 0,
        'losses': 0,
        'draws': 0,
        'rejects': 0,
    }

    bot.say(chan, 'Thanks for registering, %s. Your initial rating is %s.'
            % (player, initial_rating))


def report_game(bot, user, chan, args, outcome):
    player = user.split('!')[0]
    if player not in state['players']:
        bot.say(chan, 'Register first!')
        return

    if len([g for g in state['pending'] if g['p2'] == player]):
        bot.say(chan, 'Verify or reject your incoming claims first.')
        return

    if len(args) != 2 or args[0] != 'vs':
        bot.say(chan, 'Expected "%s vs <player>". Sorry' % outcome)
        return

    if args[1] == player:
        bot.say(chan, 'Don\'t play with yourself in public.')
        return

    opponent = state['players'].get(args[1])
    if not opponent:
        bot.say(chan, 'Can\'t find player "%s"' % args[1])
        return

    g = {
        'id': state['next_id'],
        'p1': player,
        'p2': args[1],
        'outcome': outcome,
        'date': '%s' % date.today()
    }

    state['next_id'] += 1

    state['pending'].append(g)
    bot.say(chan, 'Added unverified claim %d; ratings will be adjusted when the other party verifies it' % g['id'])


def win(bot, user, chan, args):
    report_game(bot, user, chan, args, 'win')

def loss(bot, user, chan, args):
    report_game(bot, user, chan, args, 'loss')

def draw(bot, user, chan, args):
    report_game(bot, user, chan, args, 'draw')

def show_help(bot, user, chan, args):
    bot.say(chan, 'Supported commands:')
    bot.say(chan, '  ' + ' '.join(
        '%s%s' % (cmd_prefix, k) for k in cmds.keys()))

def incoming(bot, user, chan, args):
    player = user.split('!')[0]
    if player not in state['players']:
        bot.say(chan, 'Register first!')
        return

    bot.notice(user, 'incoming claims:')
    for g in state['pending']:
        if g['p2'] == player:
            bot.notice(user, '%d: %s %s vs %s (%s)' %
                    (g['id'], g['p1'], g['outcome'], g['p2'], g['date']))

def outgoing(bot, user, chan, args):
    player = user.split('!')[0]
    if player not in state['players']:
        bot.say(chan, 'Register first!')
        return

    bot.notice(user, 'outgoing claims:')
    for g in state['pending']:
        if g['p1'] == player:
            bot.notice(user, '%d: %s %s vs %s (%s)' %
                    (g['id'], g['p1'], g['outcome'], g['p2'], g['date']))

def verify(bot, user, chan, args):
    player = user.split('!')[0]
    if player not in state['players']:
        bot.say(chan, 'Register first!')
        return

    if len(args) != 1:
        bot.say(chan, 'Sorry, expected game id')
        return

    gid = int(args[0])
    for g in state['pending']:
        if g['id'] != gid:
            continue

        if g['p2'] != player:
            bot.say(chan, 'Not your game!')
            return

        state['archived'].append(g)
        state['pending'].remove(g)

        if g['outcome'] == 'draw':
            bot.say(chan, 'No rating change.')
            state['players'][g['p1']]['draws'] += 1
            state['players'][g['p2']]['draws'] += 1
            state['players'][g['p1']]['games'] += 1
            state['players'][g['p2']]['games'] += 1
            return
        
        if g['outcome'] == 'win':
            win_name, lose_name = g['p1'], g['p2']
        else:
            win_name, lose_name = g['p2'], g['p1']

        winner = state['players'][win_name]
        loser = state['players'][lose_name]

        ra = winner['rating']
        rb = loser['rating']
        ea = 1.0 / (1.0 + 10 ** ((rb - ra)/400.0))
        eb = 1.0 / (1.0 + 10 ** ((ra - rb)/400.0))

        up = round(32 * (1 - ea))
        down = round(32 * (-eb))

        winner['rating'] += up
        loser['rating'] += down
        winner['wins'] += 1
        loser['losses'] += 1
        winner['games'] += 1
        loser['games'] += 1

        bot.say(chan, 'Ratings updated. %s now on %d (+%d). %s now on %d (%d)' % (
            win_name, winner['rating'], up,
            lose_name, loser['rating'], down))
        return
    else:
        bot.say(chan, 'Sorry, couldn\'t find your game')
        return


def reject(bot, user, chan, args):
    player = user.split('!')[0]
    if player not in state['players']:
        bot.say(chan, 'Register first!')
        return

    if len(args) != 1:
        bot.say(chan, 'Sorry, expected game id')
        return

    gid = int(args[0])
    for g in state['pending']:
        if g['id'] != gid:
            continue

        if g['p2'] != player:
            bot.say(chan, 'Not your game!')
            return

        state['pending'].remove(g)
        bot.say(chan, 'Rejected claim.')
        # cant assume this exists; added later.
        state['players'][player].setdefault('rejects', 0)
        state['players'][player]['rejects'] += 1
        return
    else:
        bot.say(chan, 'Sorry, couldn\'t find your game')


def cancel(bot, user, chan, args):
    player = user.split('!')[0]
    if player not in state['players']:
        bot.say(chan, 'Register first!')
        return

    if len(args) != 1:
        bot.say(chan, 'Sorry, expected game id')
        return

    gid = int(args[0])
    for g in state['pending']:
        if g['id'] != gid:
            continue

        if g['p1'] != player:
            bot.say(chan, 'Not your game!')
            return

        state['pending'].remove(g)
        bot.say(chan, 'Claim removed.')
        return
    else:
        bot.say(chan, 'Sorry, couldn\'t find your game')


def top(bot, user, chan, args):
    ranked = sorted(state['players'].items(), key=lambda x: -(x[1]['rating']))
    topn = ranked[0:10]
    base = 1

    for i, v in enumerate(topn):
        name, data = v
        bot.notice(user, '#%d: %s (%d)' % (base+i, name, data['rating']))


cmds = {
    'register': register,
    'win': win,
    'loss': loss,
    'draw': draw,
    'verify': verify,
    'reject': reject,
    'help': show_help,
    'incoming': incoming,
    'outgoing': outgoing,
    'top': top,
    'cancel': cancel,
}

class Bot(irc.IRCClient):
    @property
    def nickname(self):
        return self.factory.nickname

    def signedOn(self):
        print('Signed on as %s.' % self.nickname)
        self.join(self.factory.channel)

    def joined(self, channel):
        print('Joined %s.' % channel)

    def notice(self, user, msg):
        if type(msg) is unicode:
            msg = msg.encode('utf-8')
        irc.IRCClient.notice(self, user, msg)

    def say(self, channel, msg):
        if type(msg) is unicode:
            msg = msg.encode('utf-8')
        irc.IRCClient.say(self, channel, msg)

    def privmsg(self, user, channel, msg):
        if not msg.startswith(cmd_prefix):
            return

        parts = msg[len(cmd_prefix):].split(' ')
        cmd = cmds.get(parts[0])

        if not cmd:
            self.say(channel, 'Eh?')
            return

        cmd(self, user.split('!')[0], channel, parts[1:])
        save()


class BotFactory(protocol.ClientFactory):
    protocol = Bot

    def __init__(self, channel, nickname='elobot'):
        self.channel = channel
        self.nickname = nickname

    def clientConnectionLost(self, connector, reason):
        print('Connection lost. Reason: %s' % reason)
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        print('Connection failed. Reason: %s' % reason)
        connector.connect()


if __name__ == '__main__':
    try:
        load()
    except Exception as e:
        print(e)
    reactor.connectTCP('irc.freenode.org', 6667, BotFactory('#openra'))
    reactor.run()
