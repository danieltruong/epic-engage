# Copyright © 2021 Province of British Columbia
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Tests for analytics integration."""

from unittest.mock import MagicMock, patch

from met_api.utils import analytics
from met_api.utils.analytics import AnalyticsEvent, AnalyticsManager, BaseAnalyticsProvider
from met_api.utils.snowplow_tracker import SnowplowTracker as SnowplowAnalyticsProvider


class TestAnalyticsIntegration:
    """Test analytics integration and initialization."""

    def test_analytics_manager_initialization(self):
        """Test that analytics manager can be initialized with a provider."""
        manager = AnalyticsManager()
        provider = SnowplowAnalyticsProvider()
        provider.initialize({'enabled': False})

        manager.initialize(provider)

        assert manager._initialized is True
        assert manager._primary_provider == provider

    def test_snowplow_provider_initialization_disabled(self):
        """Test Snowplow provider when disabled."""
        provider = SnowplowAnalyticsProvider()
        result = provider.initialize({'enabled': False})

        assert result is True
        assert provider.is_enabled() is False

    @patch('met_api.utils.snowplow_tracker.get_tracker')
    def test_snowplow_provider_initialization_enabled(self, mock_get_tracker):
        """Test Snowplow provider when enabled."""
        mock_tracker = MagicMock()
        mock_get_tracker.return_value = mock_tracker

        provider = SnowplowAnalyticsProvider()
        result = provider.initialize({
            'enabled': True,
            'collector': 'spt.apps.gov.bc.ca',
            'app_id': 'test-app',
            'namespace': 'test-api'
        })

        assert result is True
        assert provider.is_enabled() is True

    def test_track_self_describing_event_disabled(self):
        """Test tracking self-describing event when provider is disabled."""
        provider = SnowplowAnalyticsProvider()
        provider.initialize({'enabled': False})

        result = provider.track_self_describing_event(
            schema='iglu:ca.bc.gov.met/test-event/jsonschema/1-0-0',
            data={'survey_id': 123, 'engagement_id': 456}
        )

        assert result is True  # Should succeed even when disabled

    def test_analytics_event_creation(self):
        """Test creating an analytics event."""
        event = AnalyticsEvent(
            event_type='survey_submission',
            category='survey',
            action='submit',
            label='survey-123',
            value=1.0,
            properties={'submission_id': 789},
            context={'tenant': 'EAO'}
        )

        assert event.event_type == 'survey_submission'
        assert event.category == 'survey'
        assert event.action == 'submit'
        assert event.label == 'survey-123'
        assert event.value == 1.0
        assert event.properties['submission_id'] == 789
        assert event.context['tenant'] == 'EAO'

    def test_analytics_event_to_dict(self):
        """Test converting event to dictionary."""
        event = AnalyticsEvent(
            event_type='test_event',
            category='test',
            action='test_action'
        )

        event_dict = event.to_dict()

        assert event_dict['event_type'] == 'test_event'
        assert event_dict['category'] == 'test'
        assert event_dict['action'] == 'test_action'
        assert isinstance(event_dict['properties'], dict)
        assert isinstance(event_dict['context'], dict)

    def test_convenience_function_track_event(self):
        """Test track_event convenience function when manager is not initialized."""
        # Reset the global manager
        analytics._analytics_manager = None

        event = AnalyticsEvent(
            event_type='test_event',
            category='test',
            action='test_action'
        )

        # Should not raise exception
        result = analytics.track_event(event)

        # Should return True (graceful degradation)
        assert result is True

    def test_manager_tracks_with_multiple_providers(self):
        """Test manager tracks events across multiple providers."""
        manager = AnalyticsManager()

        provider1 = SnowplowAnalyticsProvider()
        provider1.initialize({'enabled': False})

        provider2 = SnowplowAnalyticsProvider()
        provider2.initialize({'enabled': False})

        manager.initialize(provider1, [provider2])

        # Create a generic event
        event = AnalyticsEvent(
            event_type='test_event',
            category='test',
            action='test_action'
        )

        # Should track to both providers
        result = manager.track_event(event)
        assert result is True

    @patch('met_api.utils.snowplow_tracker.get_tracker')
    def test_snowplow_provider_track_event(self, mock_get_tracker):
        """Test tracking a generic event through Snowplow provider."""
        mock_tracker = MagicMock()
        mock_tracker.track_struct_event = MagicMock(return_value=True)
        mock_get_tracker.return_value = mock_tracker

        provider = SnowplowAnalyticsProvider()
        provider.initialize({'enabled': True})

        event = AnalyticsEvent(
            event_type='custom_event',
            category='custom',
            action='test',
            label='test-label'
        )

        result = provider.track_event(event)
        assert result is True

    def test_provider_handles_exception_gracefully(self):
        """Test that provider handles exceptions without crashing."""
        provider = SnowplowAnalyticsProvider()
        provider.initialize({'enabled': True})
        # Tracker is not properly initialized, but should not crash

        result = provider.track_self_describing_event(
            schema='iglu:ca.bc.gov.met/test/jsonschema/1-0-0',
            data={'test': 'data'}
        )
        # Should return True (graceful degradation) even with missing tracker
        assert result is True


class TestAnalyticsManagerFallback:
    """Test analytics manager fallback behavior."""

    def test_fallback_to_secondary_provider(self):
        """Test that manager falls back to secondary provider on primary failure."""
        manager = AnalyticsManager()

        # Primary provider that will fail
        primary = MagicMock(spec=BaseAnalyticsProvider)
        primary.track_event = MagicMock(side_effect=Exception('Primary failed'))

        # Fallback provider that succeeds
        fallback = SnowplowAnalyticsProvider()
        fallback.initialize({'enabled': False})

        manager.initialize(primary, [fallback])

        # Create a test event
        event = AnalyticsEvent(
            event_type='test_event',
            category='test',
            action='test_action'
        )

        # Should succeed due to fallback
        result = manager.track_event(event)
        assert result is True

    def test_all_providers_called(self):
        """Test that all providers are called for an event."""
        manager = AnalyticsManager()

        provider1 = MagicMock(spec=BaseAnalyticsProvider)
        provider1.track_event = MagicMock(return_value=True)

        provider2 = MagicMock(spec=BaseAnalyticsProvider)
        provider2.track_event = MagicMock(return_value=True)

        manager.initialize(provider1, [provider2])

        event = AnalyticsEvent(
            event_type='test_event',
            category='test',
            action='test_action'
        )

        manager.track_event(event)

        # Both providers should be called
        provider1.track_event.assert_called_once()
        provider2.track_event.assert_called_once()
