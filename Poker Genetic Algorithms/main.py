import argparse
import logging

from pypokerengine.api.game import setup_config, start_poker
from heuristicAI import HeuristicPlayer
from deepbet import DeepBetPlayer

init_def_prob = [
    [0.6, 0.2, 0.0, 0.2],
    [0.4, 0.4, 0.1, 0.1],
    [0.1, 0.7, 0.2, 0.0],
    [0.0, 0.6, 0.4, 0.0],
    [0.0, 0.3, 0.7, 0.0]
]

first_success = ([
    [0,  0.87531517,  0.        ,  0.12468483],
    [0,  0.83440909,  0.09665919,  0.06893172],
    [0,  0.85913968,  0.14086032,  0],
    [0,  0.50294925,  0.49705075,  0],
    [0,  0.32524572,  0.67475428,  0]
], 1.3002343540816081)

second_success = ([
    [0,  0.80496345,  0.        ,  0.19503655],
    [0,  0.67177612,  0.11862687,  0.20959701],
    [0,  0.91173247,  0.08826753,  0],
    [0,  0.64027608,  0.35972392,  0],
    [0,  0.23072949,  0.76927051,  0]
], 1.473323533073196)


def define_players(deepbet_url):
    return [
        {'name': "HE_INIT", 'algorithm': HeuristicPlayer(init_def_prob)},
        {'name': "AI_1", 'algorithm': HeuristicPlayer(*first_success)},
        {'name': "DeepBet", 'algorithm': DeepBetPlayer(deepbet_url, search_threads=128,
                                                       off_tree_actions_search_time_ms=10_000)},
        {'name': "AI_2", 'algorithm': HeuristicPlayer(*second_success)},
        {'name': "HE_INIT_2", 'algorithm': HeuristicPlayer(init_def_prob)},
        {'name': "AI_3", 'algorithm': HeuristicPlayer(*second_success)},
    ]


def players_shifted_button(deepbet_url, hand_number):
    players = define_players(deepbet_url)
    shift = hand_number % len(players)
    return players[shift:] + players[:shift]


def main():
    parser = argparse.ArgumentParser(description='Run this bot against the DeepBet')
    parser.add_argument('deepbet_url',
                        help="the base URL to connect to server (e.g. http://localhost:8080)")
    parser.add_argument('--iterations', '-i', required=True, type=int,
                        help='How many hands to play')
    parser.add_argument('--verbose', '-v', action='count', default=0,
                        help='show more verbose output')
    args = parser.parse_args()

    if args.verbose == 0:
        level = logging.WARNING
    elif args.verbose == 1:
        level = logging.INFO
    else:
        assert args.verbose >= 2
        level = logging.DEBUG
    logging.basicConfig(level=level,
                        format="[%(asctime)s] %(name)s:%(levelname)-8s %(filename)s:%(lineno)d -> %(message)s")

    for hand in range(args.iterations):
        config = setup_config(max_round=1, initial_stack=200, small_blind_amount=1)
        for p in players_shifted_button(args.deepbet_url, hand):
            config.register_player(**p)
        game_result = start_poker(config, verbose=1)
        print(game_result)


if __name__ == '__main__':
    main()
