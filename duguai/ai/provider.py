# -*- coding: utf-8 -*-
"""
给AI提供state和action的模块。该模块是对decompose的进一步处理
"""
from __future__ import annotations

from typing import List, Tuple

import numpy as np

from ai.decompose import PlayDecomposer, FollowDecomposer
from card import CARD_G1, CARD_6
from card.combo import Combo


class Hand:
    """
    对手牌进行进一步分类的类
    """

    def __init__(self, cards: List[int], d_actions):
        self._cards: List[int] = cards
        self._solo: List[np.ndarray] = []
        self._pair: List[np.ndarray] = []
        self._trio: List[np.ndarray] = []
        self._bomb: List[np.ndarray] = []
        self._plane: List[np.ndarray] = []
        self._seq_solo5: List[np.ndarray] = []
        self._seq: List[np.ndarray] = []
        self._has_rocket: bool
        self._min_solo = None
        self._max_solo = None

        self.__part_action(d_actions)

    def __part_action(self, d_actions: List[np.ndarray]) -> None:
        self._has_rocket = False
        for a in d_actions:
            if not self._has_rocket and len(a) == 2 and a[-1] == CARD_G1:
                self._has_rocket = True
            if 1 <= len(a) <= 4:
                (self.solo, self.pair, self.trio, self.bomb)[len(a) - 1].append(a)
            elif len(a) == 5 and a[0] == a[1] - 1 == a[3] - 3 == a[4] - 4:
                self.seq_solo5.append(a)
            elif len(a) % 3 == 0 and a[0] == a[2] and a[0] != a[3]:
                self.plane.append(a)
            else:
                self.seq.append(a)

    @property
    def cards(self) -> List[int]:
        """玩家原始的卡牌"""
        return self._cards

    @property
    def solo(self) -> List[np.ndarray]:
        """单"""
        return self._solo

    @property
    def pair(self) -> List[np.ndarray]:
        """对"""
        return self._pair

    @property
    def trio(self) -> List[np.ndarray]:
        """三"""
        return self._trio

    @property
    def bomb(self) -> List[np.ndarray]:
        """炸弹"""
        return self._bomb

    @property
    def plane(self) -> List[np.ndarray]:
        """飞机"""
        return self._plane

    @property
    def seq(self) -> List[np.ndarray]:
        """其它各种序列"""
        return self._seq

    @property
    def seq_solo5(self) -> List[np.ndarray]:
        """长度为5的单顺"""
        return self._seq_solo5

    @property
    def has_rocket(self) -> bool:
        """是否有王炸"""
        return self._has_rocket

    @property
    def min_solo(self) -> int:
        """强拆的最小单牌"""
        return self._min_solo

    @property
    def max_solo(self) -> int:
        """强拆的最大单牌"""
        return self._max_solo

    @max_solo.setter
    def max_solo(self, value):
        self._max_solo = value

    @min_solo.setter
    def min_solo(self, value):
        self._min_solo = value


Action = List[int]


class Provider:
    """
    给AI提供state和action的类
    @note 一个AI在整副对局中只创建并使用一个Provider对象
    """
    _LAND_LORD = 0
    _FARMER_1 = 1
    _FARMER_2 = 2

    def __init__(self, land_lord_id: int, player_id: int):
        self.__land_lord_id = land_lord_id
        self.__player_id = player_id
        self._action_provider = Provider.ActionProvider(self)
        self._state_provider = Provider.StateProvider(self)

    @property
    def identity(self) -> int:
        """
        玩家身份
        @return: 0: 地主; 1: 地主下家农民; 2: 地主上家农民
        """
        return (self.__player_id - self.__land_lord_id + 3) % 3

    def provide(self, cards: List[int], hand_p: int, hand_n: int, last_combo_owner: int, last_combo: Combo = None) \
            -> Tuple[np.ndarray, Action, Hand, Hand]:
        """
        提供状态和动作
        @param cards: 当前玩家手牌
        @param hand_p: 上一个玩家手牌数量
        @param hand_n: 下一个玩家手牌数量
        @param last_combo_owner: 上一个出牌的玩家id
        @param last_combo: 上一个要跟的Combo
        @return: 元组，(state, action, good_hand, bad_hand)
        """
        if last_combo is None:
            bad_hand = None
            good_hand, action_list = self._action_provider.provide_play(cards, hand_p, hand_n)
        else:
            good_hand, bad_hand, action_list = self._action_provider.provide_follow(cards, last_combo)

        state: np.ndarray = self._state_provider.provide(good_hand, hand_p, hand_n,
                                                         (last_combo_owner - self.__land_lord_id + 3) % 3)
        return state, action_list, good_hand, bad_hand

    class ActionProvider:
        """
        AI出牌或跟牌时，给AI提供动作的类。
        动作被化简为以下几个：
        0：空过
        x1：出单，x取【0-5】, 表示出 强行最小、最小、中、偏大、最大、强行最大的单
        x2：出对，x取【1-4】, 表示出 最小、中、偏大、最大的对
        xy3：出三，x取【0-2】, 表示出最小、中间、最大的三；y表示带单还是带对
        x5：出长度为5的顺子，x取【0-1】，表示出较小的或较大的顺子
        xy4：出一个小的炸弹, x取【0-2】，表示出小炸弹或大炸弹或王炸, y表示带单还是带双还是不带
        6：出其它各种飞机连对顺子
        """

        def __init__(self, outer: Provider):
            self._outer: Provider = outer
            self._play_decomposer: PlayDecomposer = PlayDecomposer()
            self._follow_decomposer: FollowDecomposer = FollowDecomposer()

            # 若玩家为1号农民，当2号农民只剩一张牌时，仅尝试拆一次单牌。
            self._split_min_solo: bool = True
            self.action_list: Action = []

        def _split_solo(self, cards: List[int], hand: Hand):
            self._split_min_solo = False
            min_card = np.min(cards)
            if min_card < CARD_6:
                hand.min_solo = min_card
            else:
                pair_card, trio_card = -1, -1
                if len(hand.pair):
                    pair_card: int = hand.pair[0][0]
                if len(hand.trio):
                    trio_card: int = hand.trio[0][0]
                min_card: int = min(pair_card, trio_card)
                if min_card != -1:
                    hand.min_solo = min_card

        @staticmethod
        def _add_solo_actions(hand, action_list):
            if hand.min_solo:
                action_list.append(1)
            if len(hand.solo):
                action_list.extend([11, 21, 31, 41])
            if hand.max_solo:
                action_list.append(51)

        @staticmethod
        def _add_bomb_actions(hand, action_list):
            if hand.has_rocket:
                action_list.append(14)
            if len(hand.bomb):
                if len(hand.bomb) == 1:
                    action_list.append(4)
                else:
                    action_list.extend([4, 14])
                if len(hand.solo) >= 2 or len(hand.pair):
                    action_list.append(117)
                if len(hand.pair) >= 2:
                    action_list.append(127)

        def _add_actions(self, hand: Hand):
            action_list = []
            self._add_solo_actions(hand, action_list)
            if len(hand.pair):
                action_list.extend([12, 22, 32, 42])
            if len(hand.trio):
                action_list.extend([3, 103, 103])
                if len(hand.solo):
                    action_list.extend([13, 113, 123])
                if len(hand.pair):
                    action_list.extend([23, 123, 223])
            if len(hand.seq_solo5):
                action_list.extend([5, 15])
            self._add_bomb_actions(hand, action_list)
            if len(hand.seq) > 0 or len(hand.plane) > 0:
                action_list.append(6)
            return action_list

        def provide_play(self, cards: List[int], hand_p: int, hand_n: int) -> \
                Tuple[Hand, Action]:
            """
            提供出牌时候的actions
            @param cards:
            @param hand_p:
            @param hand_n:
            """
            self.action_list: Action = []
            d_actions = self._play_decomposer.get_good_plays(cards)
            hand: Hand = Hand(cards, d_actions)

            # 一农民剩2张，地主怕出对，又没有合适的单牌，故拆出一张单牌
            if self._outer.identity == Provider._LAND_LORD:
                min_hand = min(hand_p, hand_n)
                if min_hand == 2 and len(hand.solo) == 0 and len(hand.pair):
                    hand._min_solo = hand.pair[0][0]
            elif hand_n == 1 and hand_p == 1:
                hand.max_solo = np.max(cards)
            # 一号农民拆单牌
            elif self._outer.identity == Provider._FARMER_1 and hand_n == 1 and self._split_min_solo:
                self._split_solo(cards, hand)

            return hand, self._add_actions(hand)

        def provide_follow(self, cards: List[int], last_combo: Combo) \
                -> Tuple[Hand, Hand, Action]:
            """
            提供跟牌时候的action
            @param cards:
            @param last_combo: 上一个出牌的Combo
            """
            self.action_list: Action = []
            d_actions = self._follow_decomposer.get_good_follows(cards, last_combo)
            bad_d_actions = self._follow_decomposer.get_remain_follows_no_take(cards, last_combo)
            good_hand: Hand = Hand(cards, d_actions)
            bad_hand: Hand = Hand(cards, bad_d_actions)
            action_list = [0]
            action_list.extend(self._add_actions(good_hand))
            action_list.extend(self._add_actions(bad_hand))
            return good_hand, bad_hand, list(set(action_list))

    class StateProvider:
        """
        AI出牌或跟牌时，给AI提供状态的类
        状态是一个长度为13的特征向量。特征的含义以及取值范围如下：
        （备注：// 表示整除）

        状态说明               属性名                 取值范围（均为整数）
        ------------------------------------------------------------
        f1_min(单张)          solo_min              [0, 3]
        f1_max(单张)          solo_max              [0, 3]
        f2_min(对子)          pair_min              [0, 2]
        f2_max(对子)          pair_max              [0, 2]
        f2_min(三)            trio_min              [0, 2]
        f2_max(三)            trio_max              [0, 2]
        最大单顺（长为5） // 5   seq_solo_5             [0, 2]
        存在其它牌型(不含4带2)   other_seq_count       [0, 1]
        炸弹数量（大于2记作2）    bomb_count            [0, 2]
        是否有王炸              rocket                [0, 1]
        玩家位置                player               [0, 2]
        上一个牌是谁打的         last_combo_owner      [0, 2]
        上家手牌数-1            hand_p(大于5都记作5)    [0, 5]
        下家手牌数-1            hand_n(大于5都记作5)    [0, 5]
        ------------------------------------------------------------

        f1_min(x) = switch mean(x[:2]):  [1, 4] -> 0; [5, 8] -> 1; [9,  12] -> 2; [13, 15] -> 3
        f1_max(x) = switch max(x):       [1, 4] -> 0; [5, 8] -> 1; [9,  12] -> 2; [13, 15] -> 3
        f2_min(x) = switch mean(x[:2]):  [1, 5] -> 0; [6,10] -> 1; [11, 13] -> 2
        f2_max(x) = switch max(x):       [1, 5] -> 0; [6,10] -> 1; [11, 13] -> 2
        总共有 (4+3+2+1)*(3+2+1)^2*3*2*3*2*3*3*6*6 = 4199040 种状态
        """
        STATE_LEN = 14

        @staticmethod
        def __value_to_f1(value):
            if value <= 4:
                return 0
            elif value <= 8:
                return 1
            elif value <= 12:
                return 2
            else:
                return 3

        @staticmethod
        def __value_to_f2(value):
            if value <= 5:
                return 0
            elif value <= 10:
                return 1
            else:
                return 3

        @classmethod
        def _f_min(cls, solos: List[np.ndarray], t: int = 1) -> int:
            if len(solos) == 1:
                value = solos[0][0]
            else:
                value = np.mean(np.partition(np.array(solos).ravel(), 1)[0:2])
            return cls.__value_to_f1(value) if t == 1 else cls.__value_to_f2(value)

        @classmethod
        def _f_max(cls, solos: List[np.ndarray], t: int = 1) -> int:
            value = np.max(solos)
            return cls.__value_to_f1(value) if t == 1 else cls.__value_to_f2(value)

        def __init__(self, outer: Provider):
            self._outer = outer

        def provide(self, hand: Hand, hand_p: int, hand_n: int, last_combo_owner: int) -> np.ndarray:
            """
            为AI提供状态
            @param hand: 玩家的手牌
            @param last_combo_owner: 上一个手牌是谁打的
            @param hand_p: 上一个玩家的手牌数量
            @param hand_n: 下一个玩家的手牌数量
            @return: 长度为 STATE_LEN 的特征向量
            """
            state_vector = np.zeros(Provider.StateProvider.STATE_LEN, dtype=int)
            if len(hand.solo):
                state_vector[0:2] = self._f_min(hand.solo), self._f_max(hand.solo)
            if len(hand.pair):
                state_vector[2:4] = self._f_min(hand.pair, 2), self._f_max(hand.pair, 2)
            if len(hand.trio):
                state_vector[4:6] = self._f_min(hand.pair, 2), self._f_max(hand.pair, 2)
            if len(hand.seq_solo5):
                state_vector[6] = np.max(hand.seq_solo5)
            if len(hand.seq) > 0 or len(hand.plane) > 0:
                state_vector[7] = 1
            bomb_count = 2 if len(hand.bomb) > 2 else len(hand.bomb)
            state_vector[8] = bomb_count
            state_vector[9] = hand.has_rocket
            state_vector[10:14] = self._outer.identity, last_combo_owner, hand_p, hand_n
            return state_vector
