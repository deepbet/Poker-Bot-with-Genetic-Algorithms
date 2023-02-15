import sys
import re
from datetime import datetime
from collections import defaultdict, OrderedDict
import json
import random

from helper import pp_to_array
from pypokerengine.engine.card import Card
from pypokerengine.engine.hand_evaluator import HandEvaluator

HAND_ID_START = 200_000_000


def main(f, limit=None):
    hand_id = 0
    while True:
        try:
            game_id = random.randrange(HAND_ID_START, HAND_ID_START * 2)
            parse_hand(f, game_id)
        except StopIteration:
            print(f"{hand_id} hands processed", file=sys.stderr)
            break
        print()
        hand_id += 1

        if limit:
            if hand_id == limit:
                break


PREFLOP = 'preflop'
FLOP = 'flop'
TURN = 'turn'
RIVER = 'river'
VALID_ROUNDS = [PREFLOP, FLOP, TURN, RIVER]


VALID_FINAL_STATES = ['participating', 'folded', 'allin']


def parse_hand(f, hand_id):
    hand_uuid = None
    hero, pocket = None, None
    players_number, start_stack, small_blind, big_blind = None, None, None, None
    names = []

    while True:
        line = get_next_line(f)

        if 'Game start' in line:
            m = re.search(r"UUID = ([a-z]+)", line)
            if m:
                hand_uuid = m.group(1)

            _ = get_next_line(f)
            players_number, start_stack, small_blind, big_blind = parse_start(f)
            # print(players_number, start_stack, small_blind, big_blind, file=sys.stderr)
            if big_blind is None:
                big_blind = small_blind * 2
            assert players_number >= 2, players_number
            assert start_stack >= big_blind, f"Start stack={start_stack}, bb={big_blind}"
            assert small_blind > 0, small_blind

            dt = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
            print(f"PokerStars Hand #{hand_id}: Hold'em No Limit (${small_blind}/${big_blind}) - {dt}")
            print(f"Table 'genetic-bot' {players_number}-max Seat #1 is the button")

        elif re.search(r'Round \d+ start', line):
            _ = get_next_line(f)
            pocket, players = parse_start_players_info(f)
            assert len(players) == players_number, f"{players} != {players_number}"
            for i, (name, p_id, _) in enumerate(players, 1):
                if p_id == hand_uuid:
                    hero = name
                print(f"Seat {i}: {name} (${start_stack} in chips)")
                names.append(name)

        elif f'Round result (UUID = {hand_uuid})' in line:
            _ = get_next_line(f)
            line = get_next_line(f)
            assert "-- winners --" in line
            winners, pockets = parse_winners(f)
            assert winners

            board_cards, pot, final_players = parse_final_state(f)
            pot = int(pot)
            assert len(board_cards) == 5, board_cards
            assert pot > 0
            assert len(final_players) == len(names), final_players

            actions = parse_actions(f)
            for round_ in actions:
                assert round_ in VALID_ROUNDS, f"Invalid round: {round_}"
                for action in actions[round_]:
                    action['player'] = ' '.join(action['player'].split()[:-1])
                    assert action['player'] in names, action['player']

            contributions = defaultdict(list)
            sb = actions[PREFLOP][0]
            assert sb['action'] == 'SMALLBLIND', sb
            assert sb['amount'] == small_blind, f"{sb} != {small_blind}"
            print(f"{sb['player']}: posts small blind ${sb['amount']}")
            contributions[sb['player']].append(small_blind)
            bb = actions[PREFLOP][1]
            assert bb['action'] == 'BIGBLIND', bb
            assert bb['amount'] == big_blind, f"{bb} != {big_blind}"
            print(f"{bb['player']}: posts big blind ${bb['amount']}")
            contributions[bb['player']].append(big_blind)

            print('*** HOLE CARDS ***')
            assert hero
            assert len(pocket) == 2, pocket
            pocket = cards_to_str(pocket)
            print(f'Dealt to {hero} {pocket}')

            contributions, folds = print_actions(actions, board_cards, contributions, start_stack)
            print_showdown(final_players, contributions, folds, winners, pot, board_cards, start_stack, pockets)
            break


def cards_to_str(cards, whole=False):
    if len(cards) <= 3 or whole:
        cards = ' '.join(pp_to_array(cards))
        return f'[{cards}]'

    first, last = cards[:-1], cards[-1:]
    cards = ' '.join(pp_to_array(first))
    cards_last = ' '.join(pp_to_array(last))
    return f'[{cards}] [{cards_last}]'


def print_actions(actions, board_cards, contributions, start_stack):
    folds = dict()
    for action in actions[PREFLOP][2:]:
        prev_contrib = contributions[action['player']]
        p, a = print_action(action, prev_contrib, start_stack)
        contributions[p].append(a)
        if action['action'] == 'FOLD':
            folds[p] = PREFLOP

    if FLOP in actions:
        board = cards_to_str(board_cards[:3])
        print(f'*** FLOP *** {board}')
        for action in actions[FLOP]:
            prev_contrib = contributions[action['player']]
            p, a = print_action(action, prev_contrib, start_stack)
            contributions[p].append(a)
            if action['action'] == 'FOLD':
                folds[p] = FLOP

    if TURN in actions:
        board = cards_to_str(board_cards[:4])
        print(f'*** TURN *** {board}')
        for action in actions[TURN]:
            prev_contrib = contributions[action['player']]
            p, a = print_action(action, prev_contrib, start_stack)
            contributions[p].append(a)
            if action['action'] == 'FOLD':
                folds[p] = TURN

    if RIVER in actions:
        board = cards_to_str(board_cards)
        print(f'*** RIVER *** {board}')
        for action in actions[RIVER]:
            prev_contrib = contributions[action['player']]
            p, a = print_action(action, prev_contrib, start_stack)
            contributions[p].append(a)
            if action['action'] == 'FOLD':
                folds[p] = RIVER

    # print(contributions, file=sys.stderr)
    return contributions, folds


def print_action(action, prev_contrib, start_stack):
    for key in ('paid', 'amount', 'add_amount'):
        if key in action:
            action[key] = round(action[key], 5)
    current_contrib = action.get('paid') or action.get('add_amount', 0)
    player = action['player']

    if sum(prev_contrib) + current_contrib > start_stack:
        raise ValueError(f"Bet too much for {player}: {current_contrib} (prev={prev_contrib})")

    all_in = sum(prev_contrib) + current_contrib == start_stack
    all_in_desc = " and is all-in" if all_in else ""

    if action['action'] == 'FOLD':
        print(f"{player}: folds")
    elif action['action'] == 'CALL':
        if action['paid'] == 0:
            print(f"{player}: checks")
        else:
            print(f"{player}: calls ${action['paid']}{all_in_desc}")
    elif action['action'] == 'RAISE':
        current_raise = action['add_amount']
        total_bet = action['amount']
        if current_raise == total_bet:
            print(f"{player}: bets ${total_bet}{all_in_desc}")
        else:
            print(
                f"{player}: raises ${current_raise} to ${total_bet}{all_in_desc}")
    else:
        raise ValueError(f"Invalid action: {action}")

    return player, current_contrib


def print_showdown(players, contributions, folds, winners, pot, board_cards, start_stack, pockets):
    total_contrib = {k: sum(v) for k, v in contributions.items()}
    max_contrib = max(total_contrib.values())
    # print("MAX contrib is", max_contrib, file=sys.stderr)
    max_contrib_players = sum(1 for x in total_contrib.values() if x == max_contrib)
    if max_contrib_players == 1:
        second_max_contrib = max(total_contrib.values(), key=lambda x: 0 if x == max_contrib else x)
        uncalled = round(max_contrib - second_max_contrib, 5)
        # print("SECOND MAX contrib is", second_max_contrib, file=sys.stderr)
    else:
        uncalled = 0

    for p, data in players.items():
        if total_contrib[p] == max_contrib and uncalled:
            print(f"Uncalled bet (${uncalled}) returned to {p}")
            pot -= uncalled

    board_raw = [Card.from_str(card) for card in board_cards]
    if len(pockets) > 1:
        print('*** SHOW DOWN ***')
        for name, pocket in pockets.items():
            rank = HandEvaluator.eval_hand(pocket, board_raw)
            pocket = cards_to_str([str(c) for c in pocket])
            print(f"{name}: shows {pocket} ({rank})")

    # print(players, file=sys.stderr)
    # print(winners, file=sys.stderr)
    # print(pockets, file=sys.stderr)

    # should be the same as in GameEvaluator.__calc_prize_distribution
    profit = int(pot / len(winners))
    winners_profit = dict()
    for p, data in players.items():
        p_id, status, stack = data
        left = start_stack - sum(contributions[p])
        assert left >= 0, contributions[p]
        if status != 'folded':
            if p in winners:
                assert stack > left
                collected = round(stack - left, 5)
                if collected == int(collected):
                    collected = int(collected)
                winners_profit[p] = profit + uncalled
                if uncalled:
                    if collected != profit + uncalled:
                        print(f"{p}: start {start_stack}, contrib: {contributions[p]} -> left: {left}; "
                              f"collected {collected} = (profit: {profit} + uncalled {uncalled})"
                              f"-> current stack: {stack} ", file=sys.stderr)
                    # assert collected == profit + uncalled, \
                    #        f'Collected {collected}, profit {profit}, uncalled {uncalled}'
                else:
                    assert collected == profit, \
                        f'Collected {collected}, profit {profit}'
                print(f"{p} collected ${profit} from pot")
            else:
                assert abs(stack - left) < 1e-7, \
                    f'Stack {stack}, left {left}'
        else:
            assert p not in winners, winners

    print('*** SUMMARY ***')
    rake = round(pot % len(winners), 5)
    print(f'Total pot ${round(pot, 5)} | Rake ${rake}')
    board = cards_to_str(board_cards, whole=True)
    print(f'Board {board}')

    max_rank = 0
    for i, (name, data) in enumerate(players.items(), 1):
        p_id, status, stack = data

        if status == 'folded':
            fold_round = folds[name]
            if fold_round == PREFLOP:
                fold_round_desc = "before Flop"
            elif fold_round == FLOP:
                fold_round_desc = "on the Flop"
            elif fold_round == TURN:
                fold_round_desc = "on the Turn"
            elif fold_round == RIVER:
                fold_round_desc = "on the River"
            else:
                raise ValueError(f"Bad fold round {fold_round} for {name}")

            status += f" {fold_round_desc}"

            if stack == start_stack:
                assert sum(contributions[name]) == 0, contributions[name]
                assert fold_round == PREFLOP
                status += " (didn't bet)"
        else:
            pocket = pockets.get(name)
            if pocket is None:
                status = "mucked"
            else:
                rank = HandEvaluator.eval_hand(pocket, board_raw)
                pocket = cards_to_str([str(c) for c in pocket])

                if rank < max_rank:
                    status = f'mucked {pocket}'
                else:
                    max_rank = rank

                    if name in winners:
                        profit = winners_profit[name]
                        status = f"showed {pocket} and won ${profit} with {rank}"
                    else:
                        status = f"showed {pocket} and lost with {rank}"

        name += POS[i]
        print(f'Seat {i}: {name} {status}')

    # print(players, file=sys.stderr)
    # print(winners, file=sys.stderr)
    # assert len(winners) == 1, f"Too many winners: {winners}"


POS = ["", " (button)", " (small blind)", " (big blind)", "", "", ""]


def parse_start(f):
    players_number = None
    start_stack = None
    small_blind = None
    big_blind = None
    while True:
        line = get_next_line(f)
        if '=====================' in line:
            break

        m = re.search(r"(\d) players game", line)
        if m:
            players_number = int(m.group(1))

        m = re.search(r"start stack = (\d+)", line)
        if m:
            start_stack = int(m.group(1))

        m = re.search(r"small blind = (\d+)", line)
        if m:
            small_blind = int(m.group(1))

        m = re.search(r"big blind = (\d+)", line)
        if m:
            big_blind = int(m.group(1))

    return players_number, start_stack, small_blind, big_blind


def parse_start_players_info(f):
    pocket = None
    players = []
    while True:
        line = get_next_line(f)
        if '=====================' in line:
            break

        if "-- hole card --" in line:
            line = get_next_line(f)
            pocket = re.findall(r"[CDSH][\dTJQKA]", line)
            assert len(pocket) == 2, pocket

        if "-- players information --" in line:
            players = list(parse_players_info(f))

    return pocket, players


def parse_players_info(f, include_state=False):
    if include_state:
        r = re.compile(r"\d : (.+) \(([a-z]+)\) => state : (.+), stack : ([\d.e-]+)")
    else:
        r = re.compile(r"\d : (.+) \(([a-z]+)\) => .+, stack : ([\d.e-]+)")

    while True:
        line = get_next_line(f)
        m = re.search(r, line)
        if m:
            data = m.groups()
            if include_state:
                assert len(data) == 4, data
                yield [data[0], data[1], data[2], float(data[3])]
            else:
                assert len(data) == 3, data
                yield [data[0], data[1], float(data[2])]
        else:
            break


def parse_winners(f):
    winners = []
    pockets = dict()

    winner_re = re.compile(r"- (.+) \(([a-z]+)\) => state : (.+), stack : ([\d.]+)")
    pocket_player_re = re.compile(r"- (.+) \([a-z]+\)")
    pocket_re = re.compile(r"- hole => \[(\d+), (\d+)]")

    while True:
        line = get_next_line(f)
        if '=====================' in line:
            break

        m = re.search(winner_re, line)
        if m:
            data = m.groups()
            assert len(data) == 4, data
            # yield [data[0], data[1], data[2], int(data[3])]
            winners.append(data[0])
        else:
            if '-- round state --' in line:
                pass  # no pocket info (probably all folded)
            else:
                assert '-- hand info --' in line

                while True:
                    line = get_next_line(f)
                    m = re.search(pocket_player_re, line)
                    if not m:
                        break

                    assert m, line
                    name = m.group(1)

                    line = get_next_line(f)
                    assert '- hand => ' in line
                    line = get_next_line(f)
                    m = re.search(pocket_re, line)
                    assert m
                    pocket = [Card.from_id(int(card_id)) for card_id in m.groups()]
                    pockets[name] = pocket
            return winners, pockets


def parse_final_state(f):
    while True:
        line = get_next_line(f)
        if '=====================' in line:
            break

        if "- dealer btn" in line:
            _ = get_next_line(f)

            line = get_next_line(f)
            if '- community card' in line:
                board_cards = re.findall(r"[CDSH][\dTJQKA]", line)
            else:
                board_cards = []

            line = get_next_line(f)
            if '- pot' in line:
                m = re.search(r"main = (\d+)", line)
                pot = m.group(1)
            else:
                pot = None

            line = get_next_line(f)
            assert '- players information' in line, line
            players = list(parse_players_info(f, include_state=True))
            for p in players:
                assert p[2] in VALID_FINAL_STATES, p

            players = OrderedDict((p[0], tuple(p[1:])) for p in players)
            return board_cards, pot, players


def parse_actions(f):
    current_round = None
    actions = defaultdict(list)
    while True:
        line = get_next_line(f)
        if '=====================' in line:
            break

        line = line.strip().lstrip('-').strip()
        if line.startswith('{'):
            line = line.replace("'", '"')
            actions[current_round].append(json.loads(line))
        else:
            current_round = line

    return actions


def get_next_line(input_file):
    return next(input_file).strip()


if __name__ == '__main__':
    try:
        _limit = int(sys.argv[2])
    except IndexError:
        _limit = None
    main(open(sys.argv[1]), limit=_limit)
