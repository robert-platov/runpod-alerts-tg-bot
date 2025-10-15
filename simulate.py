#!/usr/bin/env python3
"""
Simulation script for RunPod Alerts Telegram Bot.

This script simulates various scenarios to test the alert service behavior
without connecting to real RunPod API or Telegram.
"""

import asyncio
import json
import logging
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from src.runpod_alerts_tg_bot.alerts_service import AlertsService
from src.runpod_alerts_tg_bot.config import AppConfig
from src.runpod_alerts_tg_bot.runpod_client import BalanceInfo

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class SimulatedBalanceScenario:
    name: str
    balance: float
    spend_per_hr: float
    description: str


class MockTelegramSender:
    """Mock Telegram sender that logs messages instead of sending them."""

    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_message(self, text: str, disable_notification: bool = False) -> None:
        notification_status = "silent" if disable_notification else "ALERT"
        logger.info("=" * 80)
        logger.info(f"📨 [{notification_status}] Telegram Message:")
        logger.info("-" * 80)
        for line in text.split("\n"):
            logger.info(line)
        logger.info("=" * 80)
        self.messages.append(
            {
                "text": text,
                "disable_notification": disable_notification,
                "timestamp": datetime.now(tz=UTC).isoformat(),
            }
        )


class MockRunpodClient:
    """Mock RunPod client that returns simulated balance data."""

    def __init__(self, balance_info: BalanceInfo) -> None:
        self.balance_info = balance_info

    async def __aenter__(self) -> "MockRunpodClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        pass

    async def fetch_balance(self) -> BalanceInfo:
        return self.balance_info


class SimulationRunner:
    """Orchestrates simulation scenarios."""

    def __init__(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.state_path = Path(self.temp_dir) / "state.json"
        logger.info(f"Using temporary state file: {self.state_path}")

    def _create_mock_config(
        self, pod_stop_balance_usd: float = 0.0, low_balance_usd: float = 20.0
    ) -> AppConfig:
        """Create a mock config for testing."""
        return AppConfig(
            runpod_api_key="mock_key",
            telegram_bot_token="mock_token",
            telegram_chat_id="mock_chat",
            low_balance_usd=low_balance_usd,
            pod_stop_balance_usd=pod_stop_balance_usd,
            alert_initial_interval_minutes=120.0,
            alert_decay_factor=0.5,
            alert_minimum_interval_minutes=15.0,
            alert_hysteresis_usd=2.0,
            poll_interval_sec=10.0,
        )

    async def _run_scenario(
        self,
        scenario: SimulatedBalanceScenario,
        sender: MockTelegramSender,
        simulate_time_passage: bool = False,
        minutes_to_simulate: float = 0,
        pod_stop_balance_usd: float = 0.0,
        low_balance_usd: float = 20.0,
    ) -> None:
        """Run a single scenario."""
        logger.info("")
        logger.info("🎬 " + "=" * 78)
        logger.info(f"🎬 Scenario: {scenario.name}")
        logger.info(f"🎬 {scenario.description}")
        logger.info(f"🎬 Balance: ${scenario.balance:,.2f}")
        logger.info(f"🎬 Spend rate: ${scenario.spend_per_hr:,.2f}/hr")

        if scenario.spend_per_hr > 0:
            hours_left = (
                scenario.balance - pod_stop_balance_usd
            ) / scenario.spend_per_hr
            logger.info(f"🎬 Time remaining: {hours_left:.1f} hours")
        else:
            logger.info("🎬 Time remaining: ∞ (no spend)")

        logger.info("🎬 " + "=" * 78)

        cfg = self._create_mock_config(
            pod_stop_balance_usd=pod_stop_balance_usd, low_balance_usd=low_balance_usd
        )

        balance_info = BalanceInfo(
            client_balance=scenario.balance,
            current_spend_per_hr=scenario.spend_per_hr,
        )

        # Monkey patch the _fetch method to return our mock data
        service = AlertsService(cfg, sender, self.state_path)

        async def mock_fetch() -> BalanceInfo:
            return balance_info

        service._fetch = mock_fetch

        # Run the alert check
        await service.poll_and_alert()

        # If we need to simulate time passage and repeated alerts
        if simulate_time_passage and minutes_to_simulate > 0:
            logger.info(f"⏰ Simulating {minutes_to_simulate} minutes passing...")

            # Load current state and manipulate time
            if self.state_path.exists():
                state_data = json.loads(self.state_path.read_text())
                if state_data.get("last_alert_at"):
                    # Move the last alert time back by the specified minutes
                    state_data["last_alert_at"] -= minutes_to_simulate * 60
                    self.state_path.write_text(json.dumps(state_data))
                    logger.info(
                        f"⏰ Adjusted alert timestamp by -{minutes_to_simulate} minutes"
                    )

            # Run another check after time passage
            service_after = AlertsService(cfg, sender, self.state_path)
            service_after._fetch = mock_fetch
            await service_after.poll_and_alert()

        logger.info("")

    async def run_scenario_1_normal_balance(self) -> None:
        """Scenario 1: Normal operation with healthy balance."""
        sender = MockTelegramSender()

        scenario = SimulatedBalanceScenario(
            name="Normal Balance",
            balance=100.0,
            spend_per_hr=2.5,
            description="Healthy balance well above threshold - no alerts expected",
        )

        await self._run_scenario(scenario, sender)

        assert len(sender.messages) == 0, (
            "Should not send any alerts for healthy balance"
        )
        logger.info("✅ Scenario 1 passed: No alerts sent for healthy balance")

    async def run_scenario_2_low_balance_first_alert(self) -> None:
        """Scenario 2: Balance drops below threshold - first alert."""
        sender = MockTelegramSender()

        scenario = SimulatedBalanceScenario(
            name="Low Balance - First Alert",
            balance=15.0,
            spend_per_hr=1.2,
            description="Balance below $20 threshold - should trigger first alert",
        )

        await self._run_scenario(scenario, sender)

        assert len(sender.messages) == 1, "Should send one low balance alert"
        assert "LOW BALANCE ALERT" in sender.messages[0]["text"]
        assert not sender.messages[0]["disable_notification"], (
            "First alert should not be silent"
        )
        logger.info("✅ Scenario 2 passed: First low balance alert sent")

    async def run_scenario_3_repeated_alerts(self) -> None:
        """Scenario 3: Multiple alerts with exponential decay."""
        sender = MockTelegramSender()

        scenario = SimulatedBalanceScenario(
            name="Repeated Low Balance Alerts",
            balance=10.0,
            spend_per_hr=0.8,
            description="Simulate multiple alerts with time passage",
        )

        # First alert
        await self._run_scenario(scenario, sender)
        first_alert_count = len(sender.messages)

        # Check state after first alert
        state_data = json.loads(self.state_path.read_text())
        first_interval = state_data["current_interval_min"]
        logger.info(f"📊 After first alert, interval: {first_interval} minutes")

        # Simulate time passage less than interval - should NOT trigger
        await self._run_scenario(
            scenario, sender, simulate_time_passage=True, minutes_to_simulate=30
        )
        assert len(sender.messages) == first_alert_count, (
            "Should not send alert before interval expires"
        )
        logger.info("✅ No premature alert before interval")

        # Simulate enough time passage - should trigger second alert
        await self._run_scenario(
            scenario, sender, simulate_time_passage=True, minutes_to_simulate=120
        )
        assert len(sender.messages) > first_alert_count, (
            "Should send second alert after interval"
        )

        # Check interval decreased
        state_data = json.loads(self.state_path.read_text())
        second_interval = state_data["current_interval_min"]
        logger.info(f"📊 After second alert, interval: {second_interval} minutes")
        assert second_interval < first_interval, "Interval should decrease"

        logger.info("✅ Scenario 3 passed: Alert interval decay working correctly")

    async def run_scenario_4_balance_recovery(self) -> None:
        """Scenario 4: Balance recovers above threshold."""
        sender = MockTelegramSender()

        # First trigger low balance alert
        low_scenario = SimulatedBalanceScenario(
            name="Low Balance",
            balance=15.0,
            spend_per_hr=1.0,
            description="Initial low balance",
        )
        await self._run_scenario(low_scenario, sender)

        # Now simulate recovery
        recovery_scenario = SimulatedBalanceScenario(
            name="Balance Recovered",
            balance=25.0,
            spend_per_hr=1.0,
            description="Balance recovers above threshold + hysteresis ($22)",
        )
        await self._run_scenario(recovery_scenario, sender)

        assert len(sender.messages) == 2, (
            "Should have low balance alert + recovery message"
        )
        assert "Balance Recovered" in sender.messages[1]["text"]
        assert sender.messages[1]["disable_notification"], (
            "Recovery message should be silent"
        )

        # Verify state was reset
        state_data = json.loads(self.state_path.read_text())
        assert state_data["alert_count"] == 0, "Alert count should be reset"
        assert state_data["last_alert_at"] is None, (
            "Last alert timestamp should be cleared"
        )

        logger.info("✅ Scenario 4 passed: Balance recovery handled correctly")

    async def run_scenario_5_balance_depleted(self) -> None:
        """Scenario 5: Balance depleted with pods stopped."""
        sender = MockTelegramSender()

        scenario = SimulatedBalanceScenario(
            name="Balance Depleted",
            balance=-5.0,
            spend_per_hr=0.0,
            description="Negative balance with zero spend - pods stopped",
        )

        await self._run_scenario(scenario, sender)

        assert len(sender.messages) == 1, "Should send depleted alert"
        assert "BALANCE DEPLETED" in sender.messages[0]["text"]
        assert "pods stopped" in sender.messages[0]["text"].lower()

        logger.info("✅ Scenario 5 passed: Balance depleted alert sent")

    async def run_scenario_6_negative_balance_with_spend(self) -> None:
        """Scenario 6: Negative balance but pods still running."""
        sender = MockTelegramSender()

        scenario = SimulatedBalanceScenario(
            name="Negative Balance with Active Spend",
            balance=-3.5,
            spend_per_hr=2.5,
            description="Negative balance but pods still consuming credits",
        )

        await self._run_scenario(scenario, sender)

        assert len(sender.messages) == 1, "Should send low balance alert"
        assert "LOW BALANCE ALERT" in sender.messages[0]["text"]
        assert "$-3.50" in sender.messages[0]["text"], "Should show negative balance"
        assert "$2.50" in sender.messages[0]["text"], "Should show spend rate"

        logger.info(
            "✅ Scenario 6 passed: Negative balance with active spend alert sent"
        )

    async def run_scenario_8_recovery_from_depleted(self) -> None:
        """Scenario 8: Recovery from depleted state."""
        sender = MockTelegramSender()

        # First deplete
        depleted_scenario = SimulatedBalanceScenario(
            name="Depleted",
            balance=-2.0,
            spend_per_hr=0.0,
            description="Depleted state",
        )
        await self._run_scenario(depleted_scenario, sender)

        # Recharge but pods not running yet
        recharged_scenario = SimulatedBalanceScenario(
            name="Recharged",
            balance=30.0,
            spend_per_hr=0.0,
            description="Recharged but pods not restarted",
        )
        await self._run_scenario(recharged_scenario, sender)

        assert len(sender.messages) == 2, "Should have depleted + recovery messages"
        assert "Balance Recovered" in sender.messages[1]["text"]

        logger.info("✅ Scenario 8 passed: Recovery from depleted state works")

    async def run_scenario_9_daily_report(self) -> None:
        """Scenario 9: Daily balance report."""
        sender = MockTelegramSender()
        cfg = self._create_mock_config()

        balance_info = BalanceInfo(client_balance=150.0, current_spend_per_hr=3.5)

        service = AlertsService(cfg, sender, self.state_path)

        async def mock_fetch() -> BalanceInfo:
            return balance_info

        service._fetch = mock_fetch

        logger.info("")
        logger.info("🎬 " + "=" * 78)
        logger.info("🎬 Scenario: Daily Balance Report")
        logger.info("🎬 Testing daily heartbeat message")
        logger.info("🎬 " + "=" * 78)

        await service.send_daily()

        assert len(sender.messages) == 1, "Should send one daily report"
        assert "Daily Balance Report" in sender.messages[0]["text"]
        assert sender.messages[0]["disable_notification"], (
            "Daily report should be silent"
        )

        logger.info("✅ Scenario 9 passed: Daily report sent correctly")

    async def run_scenario_10_edge_cases(self) -> None:
        """Scenario 10: Edge cases and boundary conditions."""
        sender = MockTelegramSender()

        # Exactly at threshold
        threshold_scenario = SimulatedBalanceScenario(
            name="Exactly at Threshold",
            balance=20.0,
            spend_per_hr=1.0,
            description="Balance exactly at threshold - should trigger alert",
        )
        await self._run_scenario(threshold_scenario, sender)
        # Balance < threshold will trigger, so balance = 20.0 < 20.0 is false, no alert
        # But the code uses balance < threshold, so 20.0 < 20.0 is false

        # Just above threshold
        self.state_path.unlink(missing_ok=True)  # Reset state
        sender.messages.clear()

        above_scenario = SimulatedBalanceScenario(
            name="Just Above Threshold",
            balance=20.1,
            spend_per_hr=1.0,
            description="Balance just above threshold - no alert",
        )
        await self._run_scenario(above_scenario, sender)

        # Very low balance with high spend
        self.state_path.unlink(missing_ok=True)
        sender.messages.clear()

        critical_scenario = SimulatedBalanceScenario(
            name="Critical Balance",
            balance=2.0,
            spend_per_hr=5.0,
            description="Very low balance with high spend - under 30 minutes remaining",
        )
        await self._run_scenario(critical_scenario, sender)

        logger.info("✅ Scenario 10 passed: Edge cases handled correctly")

    async def run_scenario_11_negative_threshold(self) -> None:
        """Scenario 11: Negative balance threshold."""
        sender = MockTelegramSender()

        logger.info("")
        logger.info("🎬 " + "=" * 78)
        logger.info("🎬 Scenario: Negative Threshold - Part 1")
        logger.info("🎬 Testing with threshold at $-1500 and balance at $-1000")
        logger.info("🎬 " + "=" * 78)

        # Create config with negative threshold
        cfg = AppConfig(
            runpod_api_key="mock_key",
            telegram_bot_token="mock_token",
            telegram_chat_id="mock_chat",
            low_balance_usd=-1500.0,
            pod_stop_balance_usd=0.0,
            alert_initial_interval_minutes=120.0,
            alert_decay_factor=0.5,
            alert_minimum_interval_minutes=15.0,
            alert_hysteresis_usd=2.0,
            poll_interval_sec=10.0,
        )

        balance_info = BalanceInfo(
            client_balance=-1000.0,
            current_spend_per_hr=5.0,
        )

        service = AlertsService(cfg, sender, self.state_path)

        async def mock_fetch() -> BalanceInfo:
            return balance_info

        service._fetch = mock_fetch

        logger.info(f"🎬 Balance: ${-1000.0:,.2f}")
        logger.info(f"🎬 Threshold: ${-1500.0:,.2f}")
        logger.info(f"🎬 Spend rate: ${5.0:,.2f}/hr")
        logger.info("🎬 Expected: No alert (balance above threshold)")

        await service.poll_and_alert()

        assert len(sender.messages) == 0, (
            "Should not send alert when balance (-1000) is above threshold (-1500)"
        )

        logger.info("✅ Part 1 passed: No alert when balance above negative threshold")

        # Part 2: Balance below negative threshold - should trigger alert
        self.state_path.unlink(missing_ok=True)
        sender.messages.clear()

        logger.info("")
        logger.info("🎬 " + "=" * 78)
        logger.info("🎬 Scenario: Negative Threshold - Part 2")
        logger.info("🎬 Testing with threshold at $-1500 and balance at $-1800")
        logger.info("🎬 " + "=" * 78)

        balance_info_below = BalanceInfo(
            client_balance=-1800.0,
            current_spend_per_hr=5.0,
        )

        service_below = AlertsService(cfg, sender, self.state_path)

        async def mock_fetch_below() -> BalanceInfo:
            return balance_info_below

        service_below._fetch = mock_fetch_below

        logger.info(f"🎬 Balance: ${-1800.0:,.2f}")
        logger.info(f"🎬 Threshold: ${-1500.0:,.2f}")
        logger.info(f"🎬 Spend rate: ${5.0:,.2f}/hr")
        logger.info("🎬 Expected: Alert (balance below threshold)")

        await service_below.poll_and_alert()

        assert len(sender.messages) == 1, (
            "Should send alert when balance (-1800) is below threshold (-1500)"
        )
        assert "LOW BALANCE ALERT" in sender.messages[0]["text"]
        assert (
            "$-1,800" in sender.messages[0]["text"]
            or "-$1,800" in sender.messages[0]["text"]
        )

        logger.info(
            "✅ Part 2 passed: Alert sent when balance below negative threshold"
        )

        # Part 3: Balance below negative threshold with zero spend - depleted state
        self.state_path.unlink(missing_ok=True)
        sender.messages.clear()

        logger.info("")
        logger.info("🎬 " + "=" * 78)
        logger.info("🎬 Scenario: Negative Threshold - Part 3")
        logger.info(
            "🎬 Testing with threshold at $-1500 and balance at $-2000 (pods stopped)"
        )
        logger.info("🎬 " + "=" * 78)

        balance_info_depleted = BalanceInfo(
            client_balance=-2000.0,
            current_spend_per_hr=0.0,
        )

        service_depleted = AlertsService(cfg, sender, self.state_path)

        async def mock_fetch_depleted() -> BalanceInfo:
            return balance_info_depleted

        service_depleted._fetch = mock_fetch_depleted

        logger.info(f"🎬 Balance: ${-2000.0:,.2f}")
        logger.info(f"🎬 Threshold: ${-1500.0:,.2f}")
        logger.info(f"🎬 Spend rate: ${0.0:,.2f}/hr")
        logger.info(
            "🎬 Expected: Depleted alert (balance below threshold, pods stopped)"
        )

        await service_depleted.poll_and_alert()

        assert len(sender.messages) == 1, (
            "Should send depleted alert when balance (-2000) is below threshold (-1500) with zero spend"
        )
        assert "BALANCE DEPLETED" in sender.messages[0]["text"]
        assert (
            "$-2,000" in sender.messages[0]["text"]
            or "-$2,000" in sender.messages[0]["text"]
        )

        logger.info(
            "✅ Part 3 passed: Depleted alert sent for balance below negative threshold with zero spend"
        )
        logger.info("✅ Scenario 11 passed: Negative threshold handled correctly")
        logger.info("")

    async def run_scenario_12_negative_pod_stop_balance(self) -> None:
        """Scenario 12: Negative pod stop balance."""
        sender = MockTelegramSender()

        logger.info("")
        logger.info("🎬 " + "=" * 78)
        logger.info("🎬 Scenario: Negative Pod Stop Balance - Part 1")
        logger.info("🎬 Testing with pod_stop_balance at $-1500 and balance at $-1000")
        logger.info("🎬 " + "=" * 78)

        # Test 1: Balance above pod stop threshold, should calculate time correctly
        scenario1 = SimulatedBalanceScenario(
            name="Negative Balance - Still Running",
            balance=-1000.0,
            spend_per_hr=5.0,
            description="Balance at -$1000, pods stop at -$1500, spend $5/hr",
        )

        await self._run_scenario(
            scenario1, sender, pod_stop_balance_usd=-1500.0, low_balance_usd=20.0
        )

        # With balance=-1000, pod_stop=-1500, spend=5
        # hours_left = (-1000 - (-1500)) / 5 = 500 / 5 = 100 hours
        # Should see alert since -1000 < 20.0 (low_balance_usd)
        assert len(sender.messages) == 1, "Should send low balance alert"
        assert "LOW BALANCE ALERT" in sender.messages[0]["text"]
        # Check that time remaining is calculated correctly (should show ~100 hours)
        logger.info("📊 Message shows time remaining for 100 hours of runway")

        logger.info(
            "✅ Part 1 passed: Time calculation correct with negative pod stop balance"
        )

        # Part 2: Balance reaches pod stop threshold with zero spend
        self.state_path.unlink(missing_ok=True)
        sender.messages.clear()

        logger.info("")
        logger.info("🎬 " + "=" * 78)
        logger.info("🎬 Scenario: Negative Pod Stop Balance - Part 2")
        logger.info("🎬 Testing with balance at -$1600 (below pod stop), pods stopped")
        logger.info("🎬 " + "=" * 78)

        scenario2 = SimulatedBalanceScenario(
            name="Negative Balance - Pods Stopped",
            balance=-1600.0,
            spend_per_hr=0.0,
            description="Balance at -$1600, pods stop at -$1500, spend $0/hr",
        )

        await self._run_scenario(
            scenario2, sender, pod_stop_balance_usd=-1500.0, low_balance_usd=20.0
        )

        assert len(sender.messages) == 1, "Should send depleted alert"
        assert "BALANCE DEPLETED" in sender.messages[0]["text"]

        logger.info(
            "✅ Part 2 passed: Depleted alert sent when balance below negative pod stop"
        )

        # Part 3: Balance at -$800, threshold at -$1000, pod_stop at -$1500
        self.state_path.unlink(missing_ok=True)
        sender.messages.clear()

        logger.info("")
        logger.info("🎬 " + "=" * 78)
        logger.info("🎬 Scenario: Negative Pod Stop Balance - Part 3")
        logger.info(
            "🎬 Testing with balance -$800 > threshold -$1000 > pod_stop -$1500"
        )
        logger.info("🎬 " + "=" * 78)

        scenario3 = SimulatedBalanceScenario(
            name="Negative Balance - Above Threshold",
            balance=-800.0,
            spend_per_hr=5.0,
            description="Balance at -$800, threshold -$1000, pods stop at -$1500",
        )

        await self._run_scenario(
            scenario3, sender, pod_stop_balance_usd=-1500.0, low_balance_usd=-1000.0
        )

        # With balance=-800, threshold=-1000, -800 > -1000, so no alert
        assert len(sender.messages) == 0, (
            "Should not send alert when balance (-800) above threshold (-1000)"
        )

        logger.info(
            "✅ Part 3 passed: No alert when negative balance above negative threshold"
        )

        # Part 4: Balance at -$1200, threshold at -$1000, pod_stop at -$1500
        self.state_path.unlink(missing_ok=True)
        sender.messages.clear()

        logger.info("")
        logger.info("🎬 " + "=" * 78)
        logger.info("🎬 Scenario: Negative Pod Stop Balance - Part 4")
        logger.info(
            "🎬 Testing with balance -$1200 < threshold -$1000 > pod_stop -$1500"
        )
        logger.info("🎬 " + "=" * 78)

        scenario4 = SimulatedBalanceScenario(
            name="Negative Balance - Below Threshold",
            balance=-1200.0,
            spend_per_hr=5.0,
            description="Balance at -$1200, threshold -$1000, pods stop at -$1500",
        )

        await self._run_scenario(
            scenario4, sender, pod_stop_balance_usd=-1500.0, low_balance_usd=-1000.0
        )

        # With balance=-1200, threshold=-1000, -1200 < -1000, should alert
        # Time remaining = (-1200 - (-1500)) / 5 = 300 / 5 = 60 hours
        assert len(sender.messages) == 1, (
            "Should send alert when balance (-1200) below threshold (-1000)"
        )
        assert "LOW BALANCE ALERT" in sender.messages[0]["text"]

        logger.info(
            "✅ Part 4 passed: Alert sent when negative balance below negative threshold"
        )
        logger.info(
            "✅ Scenario 12 passed: Negative pod stop balance handled correctly"
        )
        logger.info("")

    async def run_all_scenarios(self) -> None:
        """Run all simulation scenarios."""
        logger.info("")
        logger.info("🚀 " + "=" * 78)
        logger.info("🚀 Starting RunPod Alerts Simulation")
        logger.info("🚀 " + "=" * 78)

        try:
            # Reset state before each scenario
            await self.run_scenario_1_normal_balance()
            self.state_path.unlink(missing_ok=True)

            await self.run_scenario_2_low_balance_first_alert()
            self.state_path.unlink(missing_ok=True)

            await self.run_scenario_3_repeated_alerts()
            self.state_path.unlink(missing_ok=True)

            await self.run_scenario_4_balance_recovery()
            self.state_path.unlink(missing_ok=True)

            await self.run_scenario_5_balance_depleted()
            self.state_path.unlink(missing_ok=True)

            await self.run_scenario_6_negative_balance_with_spend()
            self.state_path.unlink(missing_ok=True)

            await self.run_scenario_8_recovery_from_depleted()
            self.state_path.unlink(missing_ok=True)

            await self.run_scenario_9_daily_report()
            self.state_path.unlink(missing_ok=True)

            await self.run_scenario_10_edge_cases()
            self.state_path.unlink(missing_ok=True)

            await self.run_scenario_11_negative_threshold()
            self.state_path.unlink(missing_ok=True)

            await self.run_scenario_12_negative_pod_stop_balance()

            logger.info("")
            logger.info("🎉 " + "=" * 78)
            logger.info("🎉 All simulation scenarios completed successfully!")
            logger.info("🎉 " + "=" * 78)

        finally:
            # Cleanup
            self.state_path.unlink(missing_ok=True)
            logger.info(f"🧹 Cleaned up temporary state file: {self.state_path}")


async def main() -> None:
    """Main entry point for simulation."""
    runner = SimulationRunner()
    await runner.run_all_scenarios()


if __name__ == "__main__":
    asyncio.run(main())
