"""L3 匹配与调度层。"""

from umcp_core.layers.l3.matching import (
    AuctionMatch,  # NearestMatch/AuctionMatch 别名（与 CodeWiki 9.2 命名对照）
    Bidding,
    CapabilityFilter,
    CompositeBidScorer,
    CredentialFilter,
    DirectPick,
    InstantMatch,
    MatchResult,
    MatchStrategy,
    NearestMatch,  # 兼容 9.2 命名
    PreMatchFilter,
    ProposalBid,
    ReverseAuction,
    SkillMatchScorer,
    TrustThresholdFilter,
)

__all__ = [
    "MatchStrategy",
    "MatchResult",
    "PreMatchFilter",
    "InstantMatch",
    "DirectPick",
    "Bidding",
    "ReverseAuction",
    "ProposalBid",
    "CredentialFilter",
    "TrustThresholdFilter",
    "CapabilityFilter",
    "SkillMatchScorer",
    "CompositeBidScorer",
    "NearestMatch",
    "AuctionMatch",
]
