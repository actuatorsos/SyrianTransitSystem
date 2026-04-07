# Play Store Listing Draft — نقل دمشق (Damascus Transit)

## App Details

| Field | Value |
|---|---|
| **Package Name** | `sy.gov.damascus.transit` |
| **App Name (AR)** | نقل دمشق |
| **App Name (EN)** | Damascus Transit |
| **Category** | Maps & Navigation / Public Transport |
| **Content Rating** | Everyone |
| **Target Countries** | Syria (SY), MENA region |

---

## Short Description (80 chars max)

**AR:** تتبع حافلات دمشق في الوقت الفعلي — للركاب والسائقين
**EN:** Real-time Damascus bus tracking for passengers and drivers

---

## Full Description

### Arabic (primary)

**نقل دمشق** هو تطبيق النقل الذكي الرسمي لمدينة دمشق، يوفر تتبعاً فورياً لمواقع الحافلات وإدارةً شاملة للرحلات.

**للركاب:**
- 📍 تتبع الحافلات في الوقت الفعلي على الخريطة
- 🕐 معرفة أوقات الوصول المتوقعة لأقرب المحطات
- 🔔 إشعارات فورية عند اقتراب الحافلة
- 🗺️ عرض المسارات والخطوط بشكل واضح
- 📱 يعمل بدون إنترنت (وضع عدم الاتصال)

**للسائقين:**
- 📡 مشاركة الموقع الفعلي للحافلة تلقائياً
- 📸 الإبلاغ عن الحوادث بالصور مباشرةً
- 🔐 تسجيل دخول آمن ببصمة الإصبع أو التعرف على الوجه
- 📊 متابعة بيانات الرحلة والمسار

**للمدراء:**
- 📈 لوحة تحكم شاملة لجميع الرحلات
- 🚌 إدارة الأسطول والجداول الزمنية
- 📋 تقارير الأداء والإحصاءات

---

### English

**Damascus Transit** is the official smart transit application for the City of Damascus, providing real-time bus tracking and comprehensive route management.

**For Passengers:**
- Real-time bus location tracking on map
- Live ETA for nearby stops
- Push notifications when your bus approaches
- Clear route and line display
- Offline mode support

**For Drivers:**
- Automatic GPS location sharing
- Incident photo reporting
- Secure biometric login (fingerprint / Face ID)
- Live trip data dashboard

**For Managers:**
- Fleet-wide operations dashboard
- Schedule and route management
- Performance reports and analytics

---

## Screenshots Required

| Screen | Description |
|---|---|
| 1 | Passenger map view with bus locations |
| 2 | Route detail / ETA screen |
| 3 | Push notification example |
| 4 | Driver dashboard |
| 5 | Driver incident reporting |
| 6 | Biometric login screen |
| 7 | Admin fleet overview |

**Specs:** 1080×1920px or 1080×2160px, PNG, ≤8MB each.

---

## App Icon

- **Size:** 512×512px
- **Format:** PNG, no transparency
- **Current asset:** `public/icon-512x512.png` (needs production-quality version)

---

## Feature Graphic

- **Size:** 1024×500px
- **Content:** Dark green (#002623) background, gold (#b9a779) Arabic text, bus silhouette

---

## Privacy Policy URL

`https://transit.damascus.gov.sy/privacy`
*(create this page before submission)*

---

## Data Safety Section

| Data Type | Collected | Shared | Purpose |
|---|---|---|---|
| Precise location | Yes (drivers only) | No | Real-time bus tracking |
| Approximate location | Yes (passengers, opt-in) | No | Nearest stop lookup |
| Photos/videos | Yes (drivers only) | No | Incident reporting |
| Device ID | Yes | No | FCM push token |
| Financial info | No | — | — |

**Data encrypted in transit:** Yes (HTTPS/TLS 1.3)
**User can request data deletion:** Yes (via in-app settings)

---

## Release Track Checklist

- [ ] `google-services.json` placed at `android/app/google-services.json`
- [ ] Signing keystore generated and stored securely
- [ ] `versionCode` and `versionName` updated in `android/app/build.gradle`
- [ ] All 7 screenshot slots filled
- [ ] Privacy policy page live at the above URL
- [ ] Data safety questionnaire completed in Play Console
- [ ] Content rating questionnaire completed (expect "Everyone")
- [ ] Target audience: 18+ (government transit app)
- [ ] Initial release: Internal testing → Closed testing → Open testing → Production
