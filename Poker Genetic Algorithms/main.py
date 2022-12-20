from pypokerengine.api.game import setup_config, start_poker
from heuristicAI import HeuristicPlayer
from consoleAI import ConsolePlayer 

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

config = setup_config(max_round=10, initial_stack=200, small_blind_amount=1)
config.register_player(name="AI_1", algorithm=HeuristicPlayer(init_def_prob))
config.register_player(name="FIT_1", algorithm=HeuristicPlayer(*first_success))
config.register_player(name="AI_2", algorithm=HeuristicPlayer(init_def_prob))
config.register_player(name="AI_3", algorithm=HeuristicPlayer(init_def_prob))
config.register_player(name="FIT_2", algorithm=HeuristicPlayer(*second_success))
game_result = start_poker(config, verbose=1)
print(game_result)