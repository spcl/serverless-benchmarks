# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
"""Cost estimates for AWS Lambda invocations.

Prices are read from ``configs/aws_lambda_pricing.json``, a snapshot of the public
AWS price list for Lambda, stored by region and CPU architecture. The estimate
covers compute (GB-seconds) and the per-request fee of on-demand invocations.

It ignores the free tier, volume discounts, ephemeral storage above the default
and the API Gateway fee, so it is the cost of the measured invocations rather
than an actual bill.
"""

import json
from dataclasses import dataclass
from typing import Dict, Optional

from sebs.faas.function import ExecutionBilling
from sebs.utils import get_resource_path


@dataclass(frozen=True)
class LambdaPrice:
    """On-demand Lambda prices for one region and architecture.

    Attributes:
        gb_second: Price of one GB-second of compute in USD
        request: Price of one request in USD
    """

    gb_second: float
    request: float


class LambdaPricing:
    """AWS Lambda price table indexed by region and architecture.

    Attributes:
        as_of: Publication date of the price list used for the table
    """

    def __init__(self, as_of: str, prices: Dict[str, Dict[str, LambdaPrice]]):
        """Initialize the price table.

        Args:
            as_of: Publication date of the price list
            prices: Mapping from region to architecture ("x64", "arm64") to prices
        """
        self._as_of = as_of
        self._prices = prices

    @property
    def as_of(self) -> str:
        """Get the publication date of the price list.

        Returns:
            str: Date in the YYYY-MM-DD format
        """
        return self._as_of

    @staticmethod
    def deserialize(config: dict) -> "LambdaPricing":
        """Create a price table from its JSON representation.

        Args:
            config: Dictionary with "as_of" and "regions" keys

        Returns:
            LambdaPricing: The price table
        """
        prices = {
            region: {
                architecture: LambdaPrice(
                    gb_second=float(price["gb_second"]), request=float(price["request"])
                )
                for architecture, price in architectures.items()
            }
            for region, architectures in config["regions"].items()
        }
        return LambdaPricing(config["as_of"], prices)

    @staticmethod
    def load() -> "LambdaPricing":
        """Load the price table shipped with SeBS.

        Returns:
            LambdaPricing: The price table from configs/aws_lambda_pricing.json
        """
        with open(get_resource_path("configs", "aws_lambda_pricing.json"), "r") as f:
            return LambdaPricing.deserialize(json.load(f))

    def price(self, region: str, architecture: str) -> Optional[LambdaPrice]:
        """Get the prices for a region and architecture.

        Args:
            region: AWS region, e.g. "us-east-1"
            architecture: CPU architecture, "x64" or "arm64"

        Returns:
            Optional[LambdaPrice]: The prices, or None if the table has no entry
        """
        return self._prices.get(region, {}).get(architecture)

    def invocation_cost(
        self, billing: ExecutionBilling, region: str, architecture: str
    ) -> Optional[float]:
        """Estimate the cost of a single invocation.

        The compute cost is calculated from the billed time and the configured
        memory instead of the stored GB-seconds, so results written before the
        GB-seconds formula was fixed give the same cost.

        Args:
            billing: Billing data of the invocation
            region: AWS region the function ran in
            architecture: CPU architecture of the function

        Returns:
            Optional[float]: Cost in USD, or None if there is no billing data
            or no price for the region and architecture
        """
        price = self.price(region, architecture)
        if price is None or billing.billed_time is None or billing.memory is None:
            return None
        gb_seconds = (billing.billed_time / 1000.0) * (billing.memory / 1024.0)
        return gb_seconds * price.gb_second + price.request
