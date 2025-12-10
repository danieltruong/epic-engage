# Analytics Integration Guide

## Table of Contents

- [Overview](#overview)
- [Configuration](#configuration)
- [Usage](#usage)
- [Conversion Funnel Tracking](#conversion-funnel-tracking)
- [Event Schemas](#event-schemas)
- [Integration](#integration)
- [Testing](#testing)
- [Deployment](#deployment)
- [Troubleshooting](#troubleshooting)

---

## Overview

Provider-agnostic analytics tracking with Snowplow as the current implementation. **Server-side tracking bypasses ad blockers** and automatically enriches events with tenant, JWT, and request context.

### Why Backend-Only Tracking?

All analytics events are tracked from the backend to prevent ad blocker interference. Frontend analytics libraries like `window.snowplow()` can be blocked by browser extensions, resulting in incomplete data. Backend tracking ensures 100% reliable event capture.

### Auto-Context Enrichment

Every tracked event automatically includes:
- **Tenant context**: Current tenant information
- **JWT context**: User roles, username, user_id (if authenticated)
- **API request context**: Endpoint, method, IP address, user agent, timestamp  

---

## Configuration

Add to `.env`:

```bash
ANALYTICS_ENABLED=true
SNOWPLOW_ENABLED=true
SNOWPLOW_COLLECTOR=spm.apps.gov.bc.ca  # Dev/Test: spm.apps.gov.bc.ca, Prod: spt.apps.gov.bc.ca
SNOWPLOW_APP_ID=Snowplow_standalone_MET
SNOWPLOW_NAMESPACE=met-api-dev  # met-api-dev, met-api-test, met-api-prod
```

**Environment-Specific Collectors:**
- **Development/Test:** `spm.apps.gov.bc.ca` (development pipeline)
- **Production:** `spt.apps.gov.bc.ca` (production pipeline)

Change `SNOWPLOW_NAMESPACE` per environment: `met-api-dev`, `met-api-test`, `met-api-prod`

---

## Usage

### Backend Tracking (Recommended)

All analytics events should be tracked from the backend to avoid ad blocker interference.

```python
from met_api.utils.snowplow_tracker import get_tracker

tracker = get_tracker()

# Only track if analytics is enabled
if tracker.is_enabled():
    tracker.track_self_describing_event(
        schema='iglu:ca.bc.gov.met/survey-submission/jsonschema/1-0-0',
        data={
            'survey_id': 123,
            'engagement_id': 456
        }
    )
```

**Common Events:**

```python
# Email verification sent
tracker.track_self_describing_event(
    schema='iglu:ca.bc.gov.met/email-verification-sent/jsonschema/1-0-0',
    data={
        'survey_id': 123,
        'engagement_id': 456,
        'verification_token': str(verification_token)
    }
)

# Survey landing page visit
tracker.track_self_describing_event(
    schema='iglu:ca.bc.gov.met/survey-landing-page-visit/jsonschema/1-0-0',
    data={
        'survey_id': 123,
        'engagement_id': 456,
        'verification_token': token  # Can be None
    }
)

# Survey submission
tracker.track_self_describing_event(
    schema='iglu:ca.bc.gov.met/survey-submission/jsonschema/1-0-0',
    data={
        'survey_id': 123,
        'engagement_id': 456
    }
)

# Subscription email sent
tracker.track_self_describing_event(
    schema='iglu:ca.bc.gov.met/subscription-email-sent/jsonschema/1-0-0',
    data={
        'survey_id': 123,
        'engagement_id': 456,
        'subscription_type': 'ENGAGEMENT'  # or 'PROJECT'
    }
)
```

### Frontend Tracking (Page Views Only)

Frontend tracking is limited to page views only, as custom events can be blocked by ad blockers.

```typescript
// Automatic page view tracking (already implemented)
// See: met-web/src/routes/PageViewTracker.tsx

// Manual page view tracking (if needed)
window.snowplow('trackPageView');
```

**Important:** Do not use `window.snowplow()` for custom events. All custom events must be tracked from the backend.

---

## Conversion Funnel Tracking

### Email-to-Survey Conversion Funnel

The primary conversion funnel tracks users from email verification through survey completion:

**User Journey:**
1. User enters email address on engagement page
2. **Event 1**: `email-verification-sent` - Backend tracks when verification email sent
3. User receives email with unique verification link
4. User clicks link in email
5. **Event 2**: `survey-landing-page-visit` - Backend tracks when user lands on survey
6. User completes survey
7. **Event 3**: `survey-submission` - Backend tracks survey completion

### Linking Events with `verification_token`

Each email verification generates a unique `verification_token` (UUID v4) that:
- Is created by the backend when email verification is requested
- Is embedded in the email link sent to the user
- Links the "start" event (email sent) with the "end" event (landing page visit)
- Enables funnel analysis by matching events with the same token

**Example:**
```python
# Step 1: Email verification sent (email_verification_service.py)
verification_token = uuid.uuid4()
tracker.track_self_describing_event(
    schema='iglu:ca.bc.gov.met/email-verification-sent/jsonschema/1-0-0',
    data={
        'survey_id': 123,
        'engagement_id': 456,
        'verification_token': str(verification_token)  # Links to step 2
    }
)

# Step 2: User clicks email link, lands on survey (email_verification_service.py)
tracker.track_self_describing_event(
    schema='iglu:ca.bc.gov.met/survey-landing-page-visit/jsonschema/1-0-0',
    data={
        'survey_id': 123,
        'engagement_id': 456,
        'verification_token': str(verification.verification_token)  # Same token
    }
)

# Step 3: User submits survey (submission_service.py)
tracker.track_self_describing_event(
    schema='iglu:ca.bc.gov.met/survey-submission/jsonschema/1-0-0',
    data={
        'survey_id': 123,
        'engagement_id': 456
    }
)
```

### Conversion Metrics Queries

**Email to Landing Page Conversion:**
```sql
SELECT 
    COUNT(DISTINCT email_sent.verification_token) as emails_sent,
    COUNT(DISTINCT landing_page.verification_token) as landing_pages_visited,
    (COUNT(DISTINCT landing_page.verification_token) * 100.0 / 
     COUNT(DISTINCT email_sent.verification_token)) as conversion_rate
FROM email_verification_sent_events AS email_sent
LEFT JOIN survey_landing_page_visit_events AS landing_page
    ON email_sent.verification_token = landing_page.verification_token
WHERE email_sent.event_timestamp >= '2025-01-01'
```

**Average Time to Landing Page:**
```sql
SELECT 
    AVG(TIMESTAMPDIFF(SECOND, 
        email_sent.event_timestamp, 
        landing_page.event_timestamp)) / 60 as avg_minutes_to_visit
FROM email_verification_sent_events AS email_sent
INNER JOIN survey_landing_page_visit_events AS landing_page
    ON email_sent.verification_token = landing_page.verification_token
WHERE email_sent.event_timestamp >= '2025-01-01'
```

**Drop-off Analysis by Survey:**
```sql
SELECT 
    email_sent.survey_id,
    COUNT(DISTINCT email_sent.verification_token) as emails_sent,
    COUNT(DISTINCT landing_page.verification_token) as visits,
    COUNT(DISTINCT email_sent.verification_token) - 
        COUNT(DISTINCT landing_page.verification_token) as drop_offs
FROM email_verification_sent_events AS email_sent
LEFT JOIN survey_landing_page_visit_events AS landing_page
    ON email_sent.verification_token = landing_page.verification_token
WHERE email_sent.event_timestamp >= '2025-01-01'
GROUP BY email_sent.survey_id
ORDER BY drop_offs DESC
```

---

## Event Schemas

### Implemented Schemas

All schemas must be registered in the Snowplow Iglu registry before use. Contact BC Stats team to register schemas.

#### 1. Email Verification Sent

**Schema**: `iglu:ca.bc.gov.met/email-verification-sent/jsonschema/1-0-0`  
**Purpose**: Track when verification email is sent to user  
**Tracked in**: `met-api/src/met_api/services/email_verification_service.py`

```json
{
  "$schema": "http://iglucentral.com/schemas/com.snowplowanalytics.self-desc/schema/jsonschema/1-0-0#",
  "description": "Email verification sent to user",
  "self": {
    "vendor": "ca.bc.gov.met",
    "name": "email-verification-sent",
    "format": "jsonschema",
    "version": "1-0-0"
  },
  "type": "object",
  "properties": {
    "survey_id": {
      "type": "integer",
      "description": "The ID of the survey"
    },
    "engagement_id": {
      "type": "integer",
      "description": "The ID of the engagement"
    },
    "verification_token": {
      "type": "string",
      "description": "Unique verification token to link with landing page visit",
      "format": "uuid"
    }
  },
  "required": ["survey_id", "engagement_id", "verification_token"],
  "additionalProperties": false
}
```

#### 2. Survey Landing Page Visit

**Schema**: `iglu:ca.bc.gov.met/survey-landing-page-visit/jsonschema/1-0-0`  
**Purpose**: Track when user lands on survey page after clicking email link  
**Tracked in**: `met-api/src/met_api/services/email_verification_service.py`

```json
{
  "$schema": "http://iglucentral.com/schemas/com.snowplowanalytics.self-desc/schema/jsonschema/1-0-0#",
  "description": "User visited survey landing page after clicking email link",
  "self": {
    "vendor": "ca.bc.gov.met",
    "name": "survey-landing-page-visit",
    "format": "jsonschema",
    "version": "1-0-0"
  },
  "type": "object",
  "properties": {
    "survey_id": {
      "type": "integer",
      "description": "The ID of the survey"
    },
    "engagement_id": {
      "type": "integer",
      "description": "The ID of the engagement"
    },
    "verification_token": {
      "type": ["string", "null"],
      "description": "Verification token from email link (null for authenticated users)",
      "format": "uuid"
    }
  },
  "required": ["survey_id", "engagement_id"],
  "additionalProperties": false
}
```

#### 3. Survey Submission

**Schema**: `iglu:ca.bc.gov.met/survey-submission/jsonschema/1-0-0`  
**Purpose**: Track when user completes and submits survey  
**Tracked in**: `met-api/src/met_api/services/submission_service.py`

```json
{
  "$schema": "http://iglucentral.com/schemas/com.snowplowanalytics.self-desc/schema/jsonschema/1-0-0#",
  "description": "Survey submission completed",
  "self": {
    "vendor": "ca.bc.gov.met",
    "name": "survey-submission",
    "format": "jsonschema",
    "version": "1-0-0"
  },
  "type": "object",
  "properties": {
    "survey_id": {
      "type": "integer",
      "description": "The ID of the survey"
    },
    "engagement_id": {
      "type": "integer",
      "description": "The ID of the engagement"
    }
  },
  "required": ["survey_id", "engagement_id"],
  "additionalProperties": false
}
```

#### 4. Subscription Email Sent

**Schema**: `iglu:ca.bc.gov.met/subscription-email-sent/jsonschema/1-0-0`  
**Purpose**: Track when subscription verification email is sent  
**Tracked in**: `met-api/src/met_api/services/email_verification_service.py`

```json
{
  "$schema": "http://iglucentral.com/schemas/com.snowplowanalytics.self-desc/schema/jsonschema/1-0-0#",
  "description": "Subscription verification email sent to user",
  "self": {
    "vendor": "ca.bc.gov.met",
    "name": "subscription-email-sent",
    "format": "jsonschema",
    "version": "1-0-0"
  },
  "type": "object",
  "properties": {
    "survey_id": {
      "type": "integer",
      "description": "The ID of the survey"
    },
    "engagement_id": {
      "type": "integer",
      "description": "The ID of the engagement"
    },
    "subscription_type": {
      "type": "string",
      "enum": ["ENGAGEMENT", "PROJECT"],
      "description": "Type of subscription (ENGAGEMENT or PROJECT)"
    }
  },
  "required": ["survey_id", "engagement_id", "subscription_type"],
  "additionalProperties": false
}
```

### Schema Registration

**Location**: `/root/repos/epic-engage/snowplow/schemas/ca.bc.gov.met/`

**To register schemas:**
1. Send schema files to BC Stats team (BCSTATS@gov.bc.ca)
2. Request registration in DEV/TEST environment first (`spm.apps.gov.bc.ca`)
3. After validation, request production registration (`spt.apps.gov.bc.ca`)
4. Verify schemas appear in Iglu registry

---

## Integration

### Service Integration Points

Track events after successful operations. All tracking is done in the backend to avoid ad blocker interference.

**Implemented Tracking Locations:**

1. **Email Verification Service** (`met-api/src/met_api/services/email_verification_service.py`):
   - `create()` method: Tracks `email-verification-sent` and `subscription-email-sent`
   - `get_active()` method: Tracks `survey-landing-page-visit`

2. **Submission Service** (`met-api/src/met_api/services/submission_service.py`):
   - `create()` method: Tracks `survey-submission`

### Implementation Pattern

```python
from met_api.utils.snowplow_tracker import get_tracker

class YourService:
    @classmethod
    def your_method(cls, params):
        # Perform business logic first
        result = YourModel.create(params)
        
        # Track event after successful operation
        try:
            tracker = get_tracker()
            if tracker.is_enabled():
                tracker.track_self_describing_event(
                    schema='iglu:ca.bc.gov.met/your-event/jsonschema/1-0-0',
                    data={
                        'survey_id': result.survey_id,
                        'engagement_id': result.engagement_id
                    }
                )
        except Exception as exc:  # noqa: B902
            # Never let analytics failures break business logic
            current_app.logger.warning(
                f'Analytics tracking failed for your-event: {str(exc)}'
            )
        
        return result
```

### Best Practices

- **Track after success**: Only track after operation completes successfully
- **Never fail the request**: Wrap tracking in try/except to prevent analytics errors from breaking business logic
- **No PII**: Don't track personally identifiable information, passwords, or survey content
- **Check is_enabled()**: Always check if tracker is enabled before tracking
- **Add exception handling**: Use `# noqa: B902` comment to suppress linting for broad exception catching in analytics code

```bash
---

## Testing

### Unit Tests

```bash
# Run analytics integration tests
pytest tests/unit/utils/test_analytics_integration.py -v

# Run all tests
cd met-api
make test

# Test with tracking disabled
export ANALYTICS_ENABLED=false
pytest tests/unit/utils/test_analytics_integration.py -v
```

### Manual Testing

**Test Email-to-Survey Funnel:**

1. **Clear existing data** (optional):
   ```sql
   DELETE FROM email_verification WHERE email_address = 'test@example.com';
   ```

2. **Start event** - Submit email:
   - Navigate to engagement page (logged out)
   - Click "Share your Thoughts"
   - Enter email address: `test@example.com`
   - Submit form
   - Check application logs for: `Analytics: Tracked email-verification-sent`

3. **Verify email sent**:
   - Check email inbox for verification link
   - Note the `token` parameter in URL

4. **End event** - Click email link:
   - Click verification link in email
   - Survey page should load
   - Check application logs for: `Analytics: Tracked survey-landing-page-visit`

5. **Verify in Snowplow**:
   - Check browser DevTools → Network tab
   - Look for POST requests to `spm.apps.gov.bc.ca` or `spt.apps.gov.bc.ca`
   - Verify status 200 OK (collector accepts event)

6. **Verify data quality**:
   - Wait 1-2 hours for pipeline processing
   - Query Snowplow data warehouse
   - Verify events have matching `verification_token`
   - Check auto-context enrichment is present

### Mocking in Tests

```python
from unittest.mock import patch, MagicMock

@patch('met_api.utils.snowplow_tracker.get_tracker')
def test_service(mock_get_tracker):
    # Setup mock tracker
    mock_tracker = MagicMock()
    mock_tracker.is_enabled.return_value = True
    mock_get_tracker.return_value = mock_tracker
    
    # Execute service method
    result = my_service.create(data)
    
    # Verify tracking was called
    mock_tracker.track_self_describing_event.assert_called_once_with(
        'iglu:ca.bc.gov.met/survey-submission/jsonschema/1-0-0',
        {'survey_id': 123, 'engagement_id': 456}
    )
```
```

Mock tracking in tests:
```python
from unittest.mock import patch, MagicMock

@patch('met_api.utils.snowplow_tracker.get_tracker')
def test_service(mock_get_tracker):
    mock_tracker = MagicMock()
    mock_get_tracker.return_value = mock_tracker
    
    result = my_service.create(data)
    
    # Verify tracking was called
    mock_tracker.track_self_describing_event.assert_called_once_with(
        'iglu:ca.bc.gov.met/submit-survey/jsonschema/1-0-0',
        {'survey_id': 123, 'engagement_id': 456}
    )
```

---

## Deployment

### Pre-Deployment
- Install `snowplow-tracker==1.0.2` in requirements.txt
- Verify tests passing
- Ensure no PII tracked

### OpenShift Deployment

When deploying to production, ensure the correct collector endpoint:

```bash
oc process -f openshift/api.dc.yml \
  -p ENV=prod \
  -p SNOWPLOW_COLLECTOR=spt.apps.gov.bc.ca \
  -p SNOWPLOW_NAMESPACE=met-api-prod \
  ... | oc apply -f -
```

**Note:** Dev/test environments automatically use `spm.apps.gov.bc.ca` (development pipeline).

### Production Rollout
1. Deploy with `ANALYTICS_ENABLED=false`
2. Monitor for 24 hours
3. Set `ANALYTICS_ENABLED=true`
4. Monitor for 48 hours
5. Verify event data quality

### Verification

Check application logs for successful initialization:
```
Analytics initialized successfully with Snowplow provider
Snowplow initialized: collector=spt.apps.gov.bc.ca, app_id=Snowplow_standalone_MET, namespace=met-api-prod
```

**Analytics Dashboard:** https://intranet.qa.gov.bc.ca/analytics/epic-engage

### Rollback
If issues occur: Set `ANALYTICS_ENABLED=false` and restart pods

---

## Troubleshooting

**Tracker not initializing:**
- Check `ANALYTICS_ENABLED=true` in environment
- Verify `SNOWPLOW_COLLECTOR` is set
- Review application logs

**Events not appearing:**
- Verify collector endpoint is reachable
- Check network connectivity
- Validate schemas match Iglu registry

**Performance issues:**
- Set `ANALYTICS_ENABLED=false` to isolate
- Check network latency to collector

**Common errors:**
```bash
# Missing module
pip install snowplow-tracker==1.0.2

# Analytics disabled
export ANALYTICS_ENABLED=true
```

---

## Implementation

### Architecture
```
Service Layer → analytics.track_*() → AnalyticsManager → SnowplowProvider → Snowplow Collector
```

### Key Files
- `src/met_api/utils/analytics.py` - Core abstraction layer, manager, and initialization
- `src/met_api/utils/snowplow_tracker.py` - Snowplow provider (implements BaseAnalyticsProvider)
- `tests/unit/utils/test_analytics_integration.py` - Integration tests (14 tests)

### Adding New Providers

Implement `BaseAnalyticsProvider` interface (only requires `track_event` and `is_enabled`):

```python
from met_api.utils.analytics import BaseAnalyticsProvider, AnalyticsEvent

class GoogleAnalyticsProvider(BaseAnalyticsProvider):
    def initialize(self, config):
        # Setup GA
        return True
    
    def track_event(self, event: AnalyticsEvent) -> bool:
        # Map generic event to GA
        # Access event.event_type, event.category, event.action, event.properties
        return True
    
    def is_enabled(self) -> bool:
        return self._enabled

# Use in analytics.py init_analytics()
analytics.initialize_analytics(
    primary_provider=SnowplowTracker(),
    fallback_providers=[GoogleAnalyticsProvider()]
)
```

### Adding New Event Types

**No code changes needed!** Just:
1. Create Iglu schema JSON file in `/root/repos/epic-engage/snowplow/schemas/ca.bc.gov.met/your-event/jsonschema/1-0-0`
2. Send schema to BC Stats team for Iglu registry registration
3. Call `track_self_describing_event()` with schema URI + data

```python
# Backend
tracker.track_self_describing_event(
    'iglu:ca.bc.gov.met/button-click/jsonschema/1-0-0',
    {'button_name': 'submit', 'page': '/survey'}
)
```

**Schema versioning**: Use Iglu format `MODEL-REVISION-ADDITION` (e.g., `1-0-0`):
- **MODEL**: Breaking changes (incompatible with previous version)
- **REVISION**: New required fields
- **ADDITION**: New optional fields
