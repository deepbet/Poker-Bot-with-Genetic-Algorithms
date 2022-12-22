import random
import sys
import logging
from time import sleep

import pypokerengine.utils.visualize_utils as U
from pypokerengine.players import BasePokerPlayer
import helper

try:
    import requests
except ImportError:
    requirements = ['requests']
    sys.exit("Should install the requirements: `pip install {}`".format(' '.join(requirements)))


class DeepBetPlayer(BasePokerPlayer):
    def __init__(self, host, search_threads=None):
        super().__init__()
        self.api = Api(host, search_threads=search_threads, verbose=2)
        self.api.connect()
        self.game_settings = None
        self.game_id = None

    def declare_action(self, valid_actions, hole_card, round_state):
        print(U.visualize_declare_action(valid_actions, hole_card, round_state, self.uuid, show_round_state=False))
        action, amount = self.api.get_rts_action(self.game_id, valid_actions)
        return action, amount

    def receive_game_start_message(self, game_info):
        players = [{'name': p['name'], 'id': i, 'stack': p['stack']}
                   for i, p in enumerate(game_info['seats'])]
        # rotate to make a Button the last in the list
        if len(players) > 2:
            players = players[1:] + players[:1]

        self.game_settings = {
            'starting_stack': game_info['rule']['initial_stack'],
            'small_blind': game_info['rule']['small_blind_amount'],
            'players': players
        }

        print(U.visualize_game_start(game_info, self.uuid))

    def receive_round_start_message(self, round_count, hole_card, seats):
        ids = [p['uuid'] for p in seats]
        player_pos = ids.index(self.uuid)

        if len(seats) == 2:
            order = ["BigBlind", "SmallBlind"]
        else:
            order = ["Button", "SmallBlind", "BigBlind", "UnderTheGun", "Middle", "Cutoff"]
        try:
            pos = order[player_pos]
        except IndexError:
            pos = None

        private_info = [{"hole_cards": helper.pp_to_array(hole_card), "position": pos}]
        query = {'game_settings': self.game_settings, 'private_info': private_info}
        res = self.api.create_game(query)
        self.game_id = res['id']
        print(U.visualize_round_start(round_count, hole_card, seats, self.uuid))

    def receive_street_start_message(self, street, round_state):
        if street == 'flop':
            cards = round_state['community_card'][:3]
        elif street == 'turn':
            cards = round_state['community_card'][3:4]
        elif street == 'river':
            cards = round_state['community_card'][4:5]
        else:
            cards = []

        if cards:
            self.api.deal_board_cards(self.game_id, helper.pp_to_array(cards))

        print(U.visualize_street_start(street, round_state, self.uuid))

    def receive_game_update_message(self, new_action, round_state):
        last_action = round_state['action_histories'][round_state['street']][-1]
        logging.debug(round_state['action_histories'][round_state['street']])
        logging.debug(last_action)
        paid = last_action.get('paid', last_action.get('add_amount'))
        self.api.register_action(self.game_id, new_action['action'], new_action['amount'], paid)
        # do not print the round state
        print(U.visualize_game_update(new_action, round_state, self.uuid, show_round_state=False))

    def receive_round_result_message(self, winners, hand_info, round_state):
        self.api.delete_game(self.game_id)
        print(U.visualize_round_result(winners, hand_info, round_state, self.uuid))


class Api:
    def __init__(self, server_url, search_threads=None, verbose=0):
        self.server_url = server_url
        self.search_threads = search_threads
        self.verbose = verbose

    def _start_new_game_url(self):
        return '{}/games/create'.format(self.server_url)

    def _get_task_url(self, task_id):
        return '{}/async/{}'.format(self.server_url, task_id)

    def _list_all_games_url(self):
        return '{}/games'.format(self.server_url)

    def _game_status_url(self, game_id):
        return '{}/games/{}'.format(self.server_url, game_id)

    def _post_action_url(self, game_id, action, amount, paid):
        if action == "fold":
            query = "action=Fold"
        elif action == "call":
            if paid:
                query = "action=Call"
            else:
                query = "action=Check"
        elif action == "raise":
            query = f"bet={amount}"
            if self.search_threads is not None:
                query += f"&use_threads={self.search_threads}"
        else:
            query = None

        if query:
            return '{}/act/{}?{}'.format(self.server_url, game_id, query)

    def _get_action_url(self, game_id):
        return '{}/act/{}'.format(self.server_url, game_id)

    def _deal_board_cards_url(self, game_id):
        return '{}/deal/{}'.format(self.server_url, game_id)

    def connect(self):
        if self.verbose > 0:
            print("Connecting to {}...".format(self.server_url))

        resp = requests.get(self._list_all_games_url())
        if resp.status_code >= 400:
            raise ValueError(resp.text)
        return resp

    def create_game(self, create_request):
        logging.info("Creating a game: %r", create_request)
        resp = self.inspect_response(requests.post(self._start_new_game_url(), json=create_request))
        if resp.status_code >= 400:
            raise ValueError(resp.text)

        task_id = resp.json()['task_id']
        res = self.wait_task_completion(task_id)['CreatedGame']
        logging.info("Game was created: %r", res)
        return res

    def get_task_status(self, task_id, error=True):
        # logging.debug("Checking task status: %r", task_id)
        resp = self.inspect_response(requests.get(self._get_task_url(task_id)))
        if resp.status_code >= 400:
            if error:
                raise ValueError(resp.text)
            else:
                logging.warning("Response from waiting task: %r", resp.text)
        return resp

    def wait_task_completion(self, task_id, sleep_for=0.1, timeout=60, error=True):
        logging.debug("Waiting %r seconds for task status %r (every %s seconds)", timeout, task_id, sleep_for)
        for _ in range(int(timeout/sleep_for)):
            resp = self.get_task_status(task_id, error=error)

            if resp.status_code == 204:
                sleep(sleep_for)
                continue

            if resp.status_code == 200:
                return resp.json()['data']['response']
            else:
                return resp.text

        if error:
            raise ValueError(f"Timeout exceeded ({timeout}s) waiting for {task_id}")

    def delete_game(self, game_id):
        logging.info("Deleting a game: %r", game_id)
        return self.inspect_response(requests.delete(self._game_status_url(game_id)))

    def register_action(self, game_id, action, amount, paid):
        logging.debug("Register action %r(%s, paid=%s) on %r", action, amount, paid, game_id)
        url = self._post_action_url(game_id, action, amount, paid)
        if url:
            resp = self.inspect_response(requests.post(url))
            if resp.status_code >= 400:
                raise ValueError(resp.text)

            res = resp.json()
            bp_err = res.get('payload')
            if bp_err:
                logging.error(bp_err)
            task_id = res['task_id']
            self.wait_task_completion(task_id, timeout=1, error=False)

    def get_rts_action(self, game_id, valid_actions):
        logging.debug("Requesting strategy on %r", game_id)
        resp = self.inspect_response(requests.get(self._get_action_url(game_id)))
        if resp.status_code >= 400:
            raise ValueError(resp.text)

        res = resp.json()
        bp_strategy = res.get('payload')
        if bp_strategy:
            logging.warning("Received fallback: %s", bp_strategy)

        task_id = res['task_id']
        result = self.wait_task_completion(task_id)['GotStrategy']
        logging.info("Received strategy: %r", result)

        strategy = result['strategy']['repr']
        actions, probabilities = tuple(zip(*strategy))
        chosen = random.choices(actions, weights=probabilities)[0]
        logging.info("Chosen action is %r", chosen)

        [fold_action, call_action, raise_action] = valid_actions[:3]

        if chosen == "Fold":
            return fold_action['action'], fold_action['amount']

        if chosen in ("Check", "Call"):
            return call_action['action'], call_action['amount']

        max_raise = raise_action['amount']['max']
        if chosen == "AllIn":
            if max_raise > 0:
                return raise_action['action'], max_raise
            else:
                return call_action['action'], call_action['amount']

        if type(chosen) is dict:
            bet = chosen['Bet']
            if max_raise > 0:
                return raise_action['action'], bet
            else:
                return call_action['action'], call_action['amount']

        raise ValueError(f"Invalid action: {chosen}")

    def deal_board_cards(self, game_id, cards, rake=None):
        logging.debug("Dealing cards %r on %r", cards, game_id)
        data = {'cards': list(map(str, cards))}
        if rake is not None:
            data['rake'] = rake

        if self.search_threads is not None:
            data['search_hints'] = {'use_threads': str(self.search_threads)}

        logging.info("Sending board cards: %r", data)
        resp = self.inspect_response(requests.post(self._deal_board_cards_url(game_id), json=data))
        if resp.status_code >= 400:
            raise ValueError(resp.text)

        res = resp.json()
        bp_err = res.get('payload')
        if bp_err:
            logging.error(bp_err)
        task_id = res['task_id']
        self.wait_task_completion(task_id, timeout=1, error=False)

    @classmethod
    def inspect_response(cls, resp):
        logging.debug("Received response: %r on url %r", resp, resp.url)
        logging.debug("Response details: %r", resp.text)
        if resp.status_code < 400:
            assert resp.status_code // 100 == 2, resp.status_code

        return resp
