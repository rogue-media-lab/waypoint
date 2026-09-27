# JSON Vehicle Schema

Location: `~/.hermes/waypoint/vehicles.json`

## Structure

```json
{
  "vehicles": [
    {
      "vin": "EXAMPLE000000VIN0",
      "year": 2018,
      "make": "Dodge",
      "model": "Journey",
      "color_code": "PSQ",
      "interior_trim": "DLX9",
      "vehicle_type": "MPV",
      "made_in": "Mexico",
      "gvwr_lbs": 5300,
      "front_gawr_lbs": 2750,
      "rear_gawr_lbs": 2950,
      "tire_size": "225/55R19 99H",
      "rim_size": "19x7.0",
      "tire_pressure_psi": 36,
      "manufacture_date": "03/18",
      "recorded_at": "2026-05-18T17:52:00.000000",
      "service_history": [
        {
          "service": "Oil Change",
          "date": "2026-05-18",
          "mileage": null,
          "notes": "Scheduled"
        }
      ],
      "engine_swap": {
        "engine_type": "LKQ (used)",
        "labor_days": 3,
        "work_performed": [...],
        "result": "Running well"
      },
      "alignment": {
        "result": "Good - drives straight",
        "note": "Towed in",
        "test_drive": "Passed"
      }
    }
  ]
}
```

## Common Fields

| Field | Type | Description |
|-------|------|-------------|
| vin | string | 17-character VIN |
| year | integer | Model year |
| make | string | Manufacturer |
| model | string | Vehicle model |
| color_code | string | Paint code (from door jamb) |
| interior_trim | string | Interior trim code |
| recorded_at | ISO8601 | Timestamp of when added |
| service_history | array | List of services performed |

## Optional Fields (from door jamb)

- vehicle_type (MPV, sedan, etc.)
- made_in (Mexico, USA, etc.)
- gvwr_lbs / gvwr_kg
- front_gawr_lbs / rear_gawr_lbs
- tire_size
- rim_size
- tire_pressure_psi
- manufacture_date

## Service History Entry

```json
{
  "service": "Oil Change",
  "date": "2026-05-18",
  "mileage": 45000,
  "notes": "Synthetic 5W-30, PF64 filter"
}
```