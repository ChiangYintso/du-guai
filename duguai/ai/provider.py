# -*- coding: utf-8 -*-
"""
给AI提供state和action的模块。该模块是对decompose的进一步处理
"""
from __future__ import annotations

from abc import ABCMeta
from typing import List, Tuple

import numpy as np

from duguai.ai.decompose import PlayDecomposer, FollowDecomposer, PlayHand
from duguai.card.combo import Combo


def _to_le(number: int, ceil: int) -> int:
    return number if number < ceil else ceil


def _hand_to_state(hand: int) -> int:
    if hand <= 5:
        return hand - 1
    elif hand <= 9:
        return 5
    elif hand <= 14:
        return 6
    else:
        return 7


class AbstractProvider(metaclass=ABCMeta):
    """
    给AI提供state和action的类
    @note 一个AI在整副对局中只创建并使用一个Provider对象
    """
    _LAND_LORD = 0
    _FARMER_1 = 1
    _FARMER_2 = 2

    def __init__(self, player_id: int):
        self._landlord_id = None
        self._player_id = player_id

    def add_landlord_id(self, landlord_id: int):
        """
        设置地主
        @param landlord_id: 地主玩家的id
        """
        self._landlord_id = landlord_id

    def calc_identity(self, player_id: int) -> int:
        """
        计算玩家身份
        @return: 0: 地主; 1: 地主下家农民; 2: 地主上家农民
        """
        return (player_id - self._landlord_id + 3) % 3


class PlayProvider(AbstractProvider):
    """
    为出牌提供拆好的手牌、状态与动作
    """

    def __init__(self, player_id: int):
        super().__init__(player_id)
        self._play_decomposer: PlayDecomposer = PlayDecomposer()
        self._state_provider: PlayProvider.StateProvider = PlayProvider.StateProvider(self)
        self._action_provider: PlayProvider.ActionProvider = PlayProvider.ActionProvider(self)

    def provide(self, card: np.ndarray, hand_p: int, hand_n: int) -> Tuple[PlayHand, np.ndarray, List[int]]:
        """
        提供拆好的手牌、状态、动作
        @param card: 玩家手牌
        @param hand_p: 上家手牌数量
        @param hand_n: 下家手牌数量
        @return: play_hand, state_vector, action_list
        """
        play_hand: PlayHand = self._play_decomposer.get_good_plays(card)
        state_vector: np.ndarray = self._state_provider.provide(play_hand, hand_p, hand_n)
        action_list: List[int] = self._action_provider.provide(play_hand, hand_p, hand_n)
        return play_hand, state_vector, action_list

    class ActionProvider:
        """
        AI出牌时，给AI提供动作的类。
        动作被化简为以下几个：
        【0-4】出单，表示出 强行最小、小、中、大、强行最大的单
        【5-7】出对，表示出 小、中、大的对
        【8-9】出三，表示出最小、较大的三
        【10-12】出炸弹，表示出小炸弹或大炸弹或王炸
        【13-14】出长度为5的顺子，表示出较小的或较大的顺子
        【15】出其它连对顺子飞机
        【16】 出4带2
        """
        BAD_ACTION = (0, 4, 10, 11, 12)

        MIN_SOLO = 0
        MAX_SOLO = 4

        BASE_SOLO = 1
        BASE_PAIR = 5
        BASE_TRIO = 8
        BASE_FOUR = 10
        BASE_FIVE = 13

        ROCKET = 12

        OTHER_SEQ_OR_PLANE = 15
        FOUR_TAKE_TWO = 16

        ACTION_VIEW = ('强拆最小单牌', '小单', '中单', '大单', '强行最大单',
                       '小对', '中对', '大对',
                       '小三', '大三',
                       '小炸弹', '大炸弹', '王炸',
                       '小长5单顺', '大长5单顺',
                       '其它顺子/连对/飞机', '四带二')

        def __init__(self, outer: PlayProvider):
            self._play_hand: PlayHand
            self._action_list: List[int]
            self._outer: PlayProvider = outer

        def _init(self, play_hand: PlayHand, hand_p: int, hand_n: int):
            self._play_hand: PlayHand = play_hand
            self_identity = self._outer.calc_identity(self._outer._player_id)
            if self_identity == self._outer._FARMER_1:
                if hand_p == 1:
                    self._action_list = [self.MAX_SOLO]
                elif hand_n == 1:
                    self._action_list = [self.MIN_SOLO]
                else:
                    self._action_list = []
            elif self_identity == self._outer._FARMER_2:
                self._action_list = [self.MAX_SOLO] if hand_n == 1 else []
            else:
                self._action_list: List[int] = []

        def _add_actions(self, actions: List[np.ndarray], total: int, base: int) -> None:
            if actions:
                for offset in range(total):
                    if len(actions) >= offset + 1:
                        self._action_list.append(base + offset)
                    else:
                        return

        def provide(self, play_hand: PlayHand, hand_p: int, hand_n: int) -> List[int]:
            """
            提供出牌时候的actions
            @param play_hand: decompose得到的结果
            @param hand_p: 上家手牌数量
            @param hand_n: 下家手牌数量
            """
            self._init(play_hand, hand_p, hand_n)

            self._add_actions(play_hand.solos, 3, self.BASE_SOLO)
            self._add_actions(play_hand.pairs, 3, self.BASE_PAIR)
            self._add_actions(play_hand.trios, 2, self.BASE_TRIO)
            self._add_actions(play_hand.bombs, 2, self.BASE_FOUR)
            self._add_actions(play_hand.seq_solo5, 2, self.BASE_FIVE)

            if play_hand.has_rocket:
                self._action_list.append(self.ROCKET)
            if play_hand.planes or play_hand.other_seq:
                self._action_list.append(self.OTHER_SEQ_OR_PLANE)
            if play_hand.bombs_take:
                self._action_list.append(self.FOUR_TAKE_TWO)

            return self._action_list

    class StateProvider:
        """
        AI出牌时，给AI提供状态的类
        状态是一个长度为12的特征向量。特征的含义以及取值范围如下：
        （备注：// 表示整除）
        f_min <= f_max

        状态说明               属性名                 取值范围（均为整数）
        ------------------------------------------------------------
        f1_min(单张)          solo_min              [0, 3]
        f1_max(单张)          solo_max              [0, 3]
        f2_min(对子)          pair_min              [0, 2]
        f2_max(对子)          pair_max              [0, 2]
        三的数量(大于2记作2,含飞机) trios               [0, 2]
        最大单顺（长为5） // 5   seq_solo_5             [0, 2]
        存在其它牌型(不含4带2)   other_seq_count       [0, 1]
        炸弹数量（大于2记作2）    bomb_count            [0, 2]
        是否有王炸              rocket                [0, 1]
        玩家位置                player               [0, 2]
        _hand_to_state(上家手牌数) hand_p             [0, 7]
        _hand_to_state(下家手牌数)   hand_n            [0, 7]
        ------------------------------------------------------------

        f1_min(x) = switch mean(x[:2]):  [1, 4] -> 0; [5, 8] -> 1; [9,  12] -> 2; [13, 15] -> 3
        f1_max(x) = switch max(x):       [1, 4] -> 0; [5, 8] -> 1; [9,  12] -> 2; [13, 15] -> 3
        f2_min(x) = switch mean(x[:2]):  [1, 5] -> 0; [6,10] -> 1; [11, 13] -> 2
        f2_max(x) = switch max(x):       [1, 5] -> 0; [6,10] -> 1; [11, 13] -> 2
        总共有 (4+3+2+1)*(3+2+1)*3^2*2*3*2*3*8*8 = 1244160 种状态
        """
        STATE_LEN = 12

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
                return 2

        @classmethod
        def _f_min(cls, actions: List[np.ndarray], t: int = 1) -> int:
            if len(actions) == 1:
                value = actions[0][0]
            else:
                value = np.mean(np.partition(np.array(actions).ravel(), 1)[0:2])
            return cls.__value_to_f1(value) if t == 1 else cls.__value_to_f2(value)

        @classmethod
        def _f_max(cls, actions: List[np.ndarray], t: int = 1) -> int:
            value = np.max(actions)
            return cls.__value_to_f1(value) if t == 1 else cls.__value_to_f2(value)

        def __init__(self, outer: AbstractProvider):
            self._outer = outer

        def provide(self, hand: PlayHand, hand_p: int, hand_n: int) -> np.ndarray:
            """
            为AI提供状态
            @param hand: 玩家的手牌
            @param hand_p: 上一个玩家的手牌数量
            @param hand_n: 下一个玩家的手牌数量
            @return: 长度为 STATE_LEN 的特征向量
            """
            state_vector = np.zeros(PlayProvider.StateProvider.STATE_LEN, dtype=int)
            if hand.solos:
                state_vector[0:2] = self._f_min(hand.solos), self._f_max(hand.solos)
            if hand.pairs:
                state_vector[2:4] = self._f_min(hand.pairs, 2), self._f_max(hand.pairs, 2)

            trios_count = len(hand.trios) + len(hand.planes) * 2
            state_vector[4] = _to_le(trios_count, 2)
            if hand.seq_solo5:
                state_vector[5] = np.max(hand.seq_solo5) // 5

            state_vector[6] = 1 if hand.other_seq or hand.planes else 0
            state_vector[7] = _to_le(len(hand.bombs), 2)

            state_vector[8] = int(hand.has_rocket)
            state_vector[9:12] = \
                self._outer.calc_identity(self._outer._player_id), _hand_to_state(hand_p), _hand_to_state(hand_n)

            return state_vector


class FollowProvider(AbstractProvider):
    """
    提供跟牌时动作和状态的类

    跟牌状态如下：

    状态说明               属性名                                取值范围（均为整数）
    ---------------------------------------------------------------------------
    最佳拆牌的delta_q       delta_q 越大越拆得差(大于5都记作5)         [0, 5]
    玩家身份                player                                 [0, 2]
    上一个牌是谁打的         last_combo_owner                       [0, 2]
    _hand_to_state(上家手牌数)   hand_p                            [0, 7]
    _hand_to_state(上家手牌数)     hand_n                         [0, 7]
    上一个牌的数量    last_combo_len(大于5都记作5)                   [0, 5]

    ---------------------------------------------------------------------------
    6*3*3*8*8*6 = 20736
    AI跟牌时的动作被化简为以下几个：

    0：空过
    1-4：跟最小、较小、较大、最大
    5：可能拆坏牌的情况下跟最大
    6：小炸弹
    7：大炸弹
    8：王炸
    """

    PASS = 0
    FORCE_MAX = 5
    LITTLE_BOMB = 6
    BIG_BOMB = 7
    ROCKET = 8

    STATE_LEN = 6

    BAD_ACTION = (0, 5, 6, 7, 8)

    ACTION_VIEW = (
        '空过', '跟最小', '跟较小', '跟较大', '跟最大', '强行拆牌跟最大', '小炸弹', '大炸弹', '王炸'
    )

    def __init__(self, player_id: int):
        super().__init__(player_id)
        self._follow_decomposer: FollowDecomposer = FollowDecomposer()

    def __add_bomb(self, action_vector, bombs):
        if bombs:
            # 如果有王炸，王炸在bombs列表的第一个
            if len(bombs[0]) == 2:
                action_vector.append(self.ROCKET)
                if len(bombs) > 1:
                    action_vector.append(self.LITTLE_BOMB)
                if len(bombs) > 2:
                    action_vector.append(self.BIG_BOMB)
            else:
                action_vector.append(self.LITTLE_BOMB)
                if len(bombs) > 1:
                    action_vector.append(self.BIG_BOMB)

    def provide(self,
                last_combo_owner_id: int,
                hand_p: int,
                hand_n: int,
                cards: np.ndarray,
                last_combo: Combo) \
            -> Tuple[List[int], List[np.ndarray], List[np.ndarray], np.ndarray, List[int]]:
        """
        提供状态、动作向量及拆牌结果。
        @param last_combo_owner_id: 上一个combo是哪个id的玩家打的
        @param hand_p: 上家剩余手牌数
        @param hand_n: 下家剩余手牌数
        @param cards: 玩家当前手牌
        @param last_combo: 上一个出牌的Combo
        @return state, bombs, good_actions, max_actions, action_list
        """

        bombs, min_delta_q, good_actions, max_action = self._follow_decomposer.get_good_follows(cards, last_combo)

        action_vector = [self.PASS]
        if good_actions:
            for a in range(1, 5):
                if len(good_actions) >= a:
                    action_vector.append(a)
                else:
                    break

        if max_action.size > 0:
            action_vector.append(self.FORCE_MAX)

        self.__add_bomb(action_vector, bombs)

        state = [_to_le(min_delta_q, 5),
                 self.calc_identity(self._player_id),
                 self.calc_identity(last_combo_owner_id),
                 _hand_to_state(hand_p),
                 _hand_to_state(hand_n),
                 _to_le(last_combo.cards.size, 5)]

        return state, bombs, good_actions, max_action, action_vector
