"""Display-only approval requests emitted by Pips in agent-hub JSON fences."""

import json
import re


_FENCE = re.compile(r'^(`{3,}|~{3,})([^\r\n]*)$')


def _approval_card(raw):
    """Return a card only for a complete approval request object."""
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(value, dict) or value.get('action') != 'approval_request':
        return None
    summary, details = value.get('summary'), value.get('details')
    if not isinstance(summary, str) or not isinstance(details, str):
        return None
    if not summary.strip() or not details.strip() or len(summary) > 300 or len(details) > 10000:
        return None
    card = {'kind': 'approval_request', 'title': summary, 'text': details,
            'summary': summary, 'details': details, 'actions': ['Approve', "Don't"]}
    destination = value.get('destination')
    if destination is not None:
        if not isinstance(destination, str) or not destination.strip() or len(destination) > 2000:
            return None
        card['destination'] = destination
    return card


def parse_approval_requests(text):
    """Consume valid top-level approval fences and leave all other text untouched.

    A fence must begin in column zero. Other fenced code, quoted fences, nested
    fences, non-approval agent-hub blocks, and invalid JSON remain visible.
    """
    lines = text.splitlines(keepends=True)
    output, cards = [], []
    index = 0
    while index < len(lines):
        opener = _FENCE.fullmatch(lines[index].rstrip('\r\n'))
        if opener is None:
            output.append(lines[index])
            index += 1
            continue

        marker, info = opener.groups()
        end = index + 1
        while end < len(lines):
            candidate = lines[end].rstrip('\r\n')
            if re.fullmatch(re.escape(marker[0]) + '{' + str(len(marker)) + ',}[ \t]*', candidate):
                break
            end += 1
        if end == len(lines):
            output.extend(lines[index:])
            break

        block = lines[index:end + 1]
        card = (_approval_card(''.join(lines[index + 1:end]))
                if marker[0] == '`' and marker == '```' and info.strip().lower() == 'agent-hub'
                else None)
        if card is None:
            output.extend(block)
        else:
            cards.append(card)
        index = end + 1
    return ''.join(output), cards


class ApprovalMixin:
    """Small helpers for Hub's existing card-decision send and react flows."""

    @staticmethod
    def approval_response(card, action):
        if card.get('kind') != 'approval_request' or action not in ('Approve', "Don't"):
            raise ValueError('Unknown approval action.')
        if action == 'Approve':
            return 'Yes, approved: ' + card['summary'] + ' — exactly as shown.'
        return "No, don't do that."

    @staticmethod
    def approval_card_index(cards):
        return next((i for i, card in enumerate(cards)
                     if isinstance(card, dict) and card.get('kind') == 'approval_request'), None)

    @classmethod
    def approval_reaction(cls, cards, emoji):
        """Map a decision reaction only when one eligible approval exists."""
        if emoji not in ('👍', '✅', '👎'):
            return None
        targets = cls.reaction_targets(cards, guide_message=True)
        if len(targets) != 1 or targets[0][0] != 'approval':
            return None
        index = targets[0][1]
        return index, ("Don't" if emoji == '👎' else 'Approve')

    @staticmethod
    def reaction_targets(cards, decided_indices=(), guide_message=False):
        """List undecided actionable card indices for a message-level reaction."""
        decided = set(decided_indices)
        targets = []
        for index, card in enumerate(cards):
            if index in decided or not isinstance(card, dict) or card.get('decision'):
                continue
            if card.get('kind') == 'proposal':
                if guide_message and card.get('status') in (None, 'pending'):
                    targets.append(('guide', index))
            elif card.get('kind') == 'approval_request':
                targets.append(('approval', index))
            elif isinstance(card.get('actions'), list) and card['actions']:
                targets.append(('card', index))
        return targets
