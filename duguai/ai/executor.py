# -*- coding: utf-8 -*-
"""
执行动作的模块
@author 江胤佐
"""
from typing import List

import numpy as np

from duguai.card import CARD_G1, CARD_G0
from .decompose import PlayHand
from .provider import PlayProvider, FollowProvider

PA = PlayProvider.ActionProvider


def _choose_play(play_hand, action: int) -> np.ndarray:
    if 1 <= action <= 3:
        action_list = play_hand.solos
        offset = action - 1
    elif action < PA.BASE_TRIO:
        action_list = play_hand.pairs
        offset = action - PA.BASE_PAIR
    elif action < PA.BASE_FOUR:
        action_list = play_hand.trios_take
        offset = action - PA.BASE_TRIO
    elif action < PA.BASE_FIVE:
        action_list = play_hand.bombs
        offset = action - PA.BASE_FOUR
    elif action < 15:
        action_list = play_hand.seq_solo5
        offset = action - PA.BASE_FIVE
    else:
        raise ValueError('action: %d错误' % action)

    if offset == 0:
        return action_list[0]
    elif offset == 1:
        return action_list[len(action_list) // 2]
    elif offset == 2:
        return action_list[-1]
    else:
        raise ValueError('play_strength 必须在1-3当中')


def execute_play(play_hand: PlayHand, action: int) -> np.ndarray:
    """
    执行出牌操作
    @param play_hand: 经过拆牌后的play_hand对象
    @param action: Q-learning算法挑选出来的动作
    @return: 数组，表示要出的牌
    """

    if action == PA.MIN_SOLO:
        return np.array([play_hand.min_solo])
    elif action == PA.MAX_SOLO:
        return np.array([play_hand.max_solo])
    elif action == PA.ROCKET:
        return np.array([CARD_G0, CARD_G1])
    elif action == PA.OTHER_SEQ_OR_PLANE:
        if play_hand.other_seq:
            return play_hand.other_seq[0]
        return play_hand.planes_take[0]
    elif action == PA.FOUR_TAKE_TWO:
        return play_hand.bombs_take[0]

    return _choose_play(play_hand, action)


def execute_follow(action: int, bombs: List[np.ndarray], good_actions: List[np.ndarray], max_actions: np.ndarray) \
        -> np.ndarray:
    """
    执行跟牌操作
    @param action: Q-learning挑选出的动作
    @param bombs: 炸弹列表
    @param good_actions: 好的拆牌动作列表
    @param max_actions: 最大拆牌动作
    @return: 数组，表示要出的牌
    """
    if action == FollowProvider.PASS:
        return np.zeros(0, dtype=int)
    if action == FollowProvider.ROCKET:
        return np.array([CARD_G0, CARD_G1])
    if action == FollowProvider.FORCE_MAX:
        return max_actions
    if action == FollowProvider.LITTLE_BOMB:
        return bombs[0]
    if action == FollowProvider.BIG_BOMB:
        return bombs[-1]

    return (
        good_actions[0],
        good_actions[len(good_actions) // 2],
        good_actions[int(len(good_actions) // 1.5)],
        good_actions[-1]
    )[action - 1]
