"""I03 history split: relabel named endpoint pieces of one cohort into history-distinct sub-cohorts (I05-2).

A cohort carries one raw history (I05 keys raw plastic history, bond, compaction and elastic memory by cohort). When
an update would give pieces of one cohort different histories, the update is not averaged and no value is kept for
all: the pieces are first split into sub-cohorts, one per distinct history, in the same atomic step as the interval
(tectonics/docs/I03_SPHERICAL_NETWORK.md section 7, "History split"). A split is carried in the interval's Motion
(``history_splits``), so it is bound into the motion identity, stored with the step and applied again on restore.

It is applied last, after the motion rows, any mesh change, regional returns and events, on the endpoint material.
Each named piece keeps its exact stock row, so every per-column sum, every exact account and every face's occupancy
allowance is unchanged. A sub-cohort keeps its parent's material, origin and formation interval (no age is reset) and
takes the history reference the split supplies; its identity is derived, bounded and never nests its parent's name.

SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import dataclass
import hashlib

import numpy as np

from . import integration_sphere as _sphere
from ._validation import TectonicsError
from .materials import _json, _name


PREFIX = 'split:'


class SplitRefused(TectonicsError):
    """A history split that is not admitted; the interval is refused whole."""


@dataclass(frozen=True, slots=True)
class HistorySplit:
    """Split ``cohort_id``: each group (history_id, face IDs) becomes one sub-cohort of the pieces in those faces.

    Pieces of the cohort in faces no group names stay in the cohort. Groups are sorted by history reference and their
    faces by ID, so one split has one record.
    """
    cohort_id: str
    groups: tuple

    def __post_init__(self):
        cohort = _checked_name(self.cohort_id, 'split cohort')
        if type(self.groups) not in (tuple, list) or not self.groups:
            raise SplitRefused('a history split of %r names at least one group: an empty split changes nothing '
                               '(no-op split)' % cohort)
        groups, seen_faces = [], set()
        for group in self.groups:
            if type(group) not in (tuple, list) or len(group) != 2:
                raise SplitRefused('a split group is (history_id, face IDs)')
            history = _checked_name(group[0], 'sub-cohort history reference')
            faces = group[1]
            if type(faces) not in (tuple, list) or not faces:
                raise SplitRefused('every sub-cohort of a split of %r holds at least one piece' % cohort)
            faces = tuple(sorted(_checked_name(face, 'split face') for face in faces))
            if len(set(faces)) != len(faces) or seen_faces & set(faces):
                raise SplitRefused('a piece of %r is named twice in one split' % cohort)
            seen_faces.update(faces)
            groups.append((history, faces))
        groups.sort()
        if len({history for history, _ in groups}) != len(groups):
            raise SplitRefused('the sub-cohorts of one split take distinct history references')
        object.__setattr__(self, 'cohort_id', cohort)
        object.__setattr__(self, 'groups', tuple(groups))

    def record(self):
        return dict(cohort_id=self.cohort_id, groups=[[history, list(faces)] for history, faces in self.groups])

    @staticmethod
    def from_record(row):
        try:
            split = HistorySplit(row['cohort_id'], tuple((history, tuple(faces)) for history, faces in row['groups']))
        except (KeyError, TypeError, ValueError) as exc:
            raise SplitRefused('the stored history split is incomplete') from exc
        if _json(split.record()) != _json(dict(row)):
            raise SplitRefused('the stored history split does not reproduce its record')
        return split


def _checked_name(value, label):
    try:
        return _name(value, label)
    except TectonicsError as exc:
        raise SplitRefused(str(exc)) from exc


def checked(splits):
    """The splits of one motion: typed, one per cohort, sorted by cohort."""
    if type(splits) not in (tuple, list) or any(type(item) is not HistorySplit for item in splits):
        raise SplitRefused('history splits are HistorySplit records')
    ordered = tuple(sorted(splits, key=lambda item: item.cohort_id))
    if len({item.cohort_id for item in ordered}) != len(ordered):
        raise SplitRefused('a cohort is split at most once in one interval')
    return ordered


def sub_cohort_id(cohort_id, end_step, history_id):
    """The derived identity of one sub-cohort: bounded, deterministic, independent of how often a cohort was split."""
    digest = hashlib.sha256(_json([cohort_id, int(end_step), history_id])).hexdigest()
    return PREFIX+digest[:32]


def _returned_cohorts(returns):
    named = set()
    for item in returns:
        for _, face in item.pieces:
            named.update(cohort for cohort, _ in face)
    return named


def applied(network, material, splits, end_step, returns, budget=None):
    """(material with the splits applied, (parent indices, child indices) into its cohorts) on the endpoint network.

    Refused whole when a split names an unknown cohort or a face holding none of its pieces, would leave a sub-cohort
    without a piece, covers every piece of its cohort with one group (no-op) or with several (the parent would keep
    no piece, so cohorts could outnumber pieces), reuses the parent's history reference,
    derives a sub-cohort identity already in use, or splits a cohort a regional return of the same interval carries.
    """
    cohorts = {record.cohort_id: record for record in material.cohorts}
    returned = _returned_cohorts(returns)
    face_ids = network.face_ids
    piece_face, piece_cohort, stock = material._face, material._cohort, material._stock
    old_ids = [record.cohort_id for record in material.cohorts]
    relabel, born = {}, []
    for split in splits:
        parent = cohorts.get(split.cohort_id)
        if parent is None:
            raise SplitRefused('a history split names cohort %r, which this state does not carry (unknown or foreign '
                               'piece)' % split.cohort_id)
        if split.cohort_id in returned:
            raise SplitRefused('cohort %r is carried by a regional return of this interval; it is not split in the '
                               'same interval' % split.cohort_id)
        index = old_ids.index(split.cohort_id)
        held = {face_ids[int(piece_face[row])]: row for row in np.flatnonzero(piece_cohort == index)}
        named = [face for _, faces in split.groups for face in faces]
        missing = [face for face in named if face not in held]
        if missing:
            raise SplitRefused('a history split of %r names face %r, which holds no piece of it (unknown or foreign '
                               'piece)' % (split.cohort_id, missing[0]))
        if len(split.groups) == 1 and len(named) == len(held):
            raise SplitRefused('a single group holding every piece of %r leaves no history distinct: no-op split'
                               % split.cohort_id)
        if len(named) == len(held):
            raise SplitRefused('the groups of a split of %r name every piece and would leave the parent cohort '
                               'without one: one history stays in the parent, so its pieces are not named'
                               % split.cohort_id)
        for history, faces in split.groups:
            if history == parent.history_id:
                raise SplitRefused('a sub-cohort of %r takes the history reference its parent already holds'
                                   % split.cohort_id)
            child = sub_cohort_id(split.cohort_id, end_step, history)
            if child in cohorts or any(child == name for name, _ in born):
                raise SplitRefused('the derived sub-cohort %r is already in use: a split never changes material, origin '
                                   'or formation of an existing cohort' % child)
            born.append((child, _sphere.Cohort(child, parent.material_id, parent.origin_id, parent.formation_start_s,
                                               parent.formation_end_s, history)))
            for face in faces:
                relabel[held[face]] = child
    records = tuple(sorted(list(material.cohorts)+[record for _, record in born], key=lambda r: r.cohort_id))
    position = {record.cohort_id: i for i, record in enumerate(records)}
    names = [relabel.get(row, old_ids[int(piece_cohort[row])]) for row in range(len(piece_face))]
    cohort = np.array([position[name] for name in names], dtype=np.int64)
    order = np.lexsort((cohort, piece_face))
    try:
        result = _sphere._material(network, material.phases, material.enthalpy_basis, records, material.exteriors,
                                   material.stock_link, piece_face[order], cohort[order], stock[order],
                                   material._initial, material._supplied, material._rounding, material._allowance,
                                   budget, checked=(), occupancy_allowance=material._occupancy_allowance)
    except TectonicsError as exc:
        raise SplitRefused('the split material is not issued: '+str(exc)) from exc
    parents = {child: split.cohort_id for split in splits for history, _ in split.groups
               for child in (sub_cohort_id(split.cohort_id, end_step, history),)}
    pairs = sorted((position[parent], position[child]) for child, parent in parents.items())
    lineage = (np.array([p for p, _ in pairs], dtype=np.int64), np.array([c for _, c in pairs], dtype=np.int64))
    return result, lineage
