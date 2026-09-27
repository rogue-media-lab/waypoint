# Vehicle Identification Pitfalls & Notes

## VIN Decode Trim Limitations

The NHTSA API `decode-vin` endpoint (used by `vehicle_db.py decode-vin`) frequently returns `trim: null` for many vehicles—including almost all Nissan models. The API resolves **make, model, year, engine, body class, and drive type**, but the **marketing trim package** (S, SV, SL, SE, etc.) is often absent from publicly queryable fields.

**Rule:** Do not promise the user a trim level based solely on the VIN unless the decode explicitly returns it. Default to asking the user or using visual identification cues.

## Make/Model-Specific Identification Notes

### 2015 Nissan Rogue
*   **Trims in 2015:** S, SV, SL. There is **no SE** trim for this year.
*   **If VIN decode fails to yield trim**, use these visual cues (or ask the user to verify):
    *   **S:** Physical key ignition (not push-button).
    *   **SV:** Push-button start (keyless entry); typically cloth or partial-leather seats.
    *   **SL:** Push-button start + leather seating + panoramic moonroof / navigation.
    *   **Third-row seat:** Optional on S or SV via the *Family Package*.
*   **Label trap:** The door jamb certification label shows a `TRIM:` field (e.g., `TRIM: G ZS30A`). This is the **interior color/material code**, not the marketing trim package. Do not confuse the two.
*   **Platform code:** `T32` on the model line label confirms standard Rogue (not Rogue Select, which was the previous generation `S35` sold alongside in some years).
