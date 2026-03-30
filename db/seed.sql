-- ============================================================
-- DamascusTransit Seed Data
-- 8 routes, 42 stops, 24 vehicles, 1 admin user
-- ============================================================

-- Seed users: generate a bcrypt hash before running this seed:
--   python3 -c "import bcrypt; print(bcrypt.hashpw(b'YOUR_STRONG_PASSWORD', bcrypt.gensalt()).decode())"
-- Replace CHANGE_ME_HASH with the generated hash. Never commit real passwords or hashes of known passwords.
INSERT INTO users (email, password_hash, full_name, full_name_ar, role, phone) VALUES
('admin@damascustransit.sy', 'CHANGE_ME_HASH', 'System Admin', 'مدير النظام', 'admin', '+963000000001'),
('dispatcher@damascustransit.sy', 'CHANGE_ME_HASH', 'Operations Center', 'مركز العمليات', 'dispatcher', '+963000000002');

-- ============================================================
-- STOPS (42 real Damascus locations)
-- ============================================================

INSERT INTO stops (stop_id, name, name_ar, location, has_shelter) VALUES
('S001', 'Marjeh Square', 'ساحة المرجة', ST_SetSRID(ST_MakePoint(36.3025, 33.5105), 4326), true),
('S002', 'Hamidiyeh Souq', 'سوق الحميدية', ST_SetSRID(ST_MakePoint(36.3065, 33.5115), 4326), true),
('S003', 'Umayyad Square', 'ساحة الأمويين', ST_SetSRID(ST_MakePoint(36.2920, 33.5130), 4326), true),
('S004', 'Baramkeh', 'البرامكة', ST_SetSRID(ST_MakePoint(36.2940, 33.5060), 4326), true),
('S005', 'Mezzeh Highway', 'أوتوستراد المزة', ST_SetSRID(ST_MakePoint(36.2600, 33.5050), 4326), true),
('S006', 'Mezzeh 86', 'مزة 86', ST_SetSRID(ST_MakePoint(36.2450, 33.5010), 4326), false),
('S007', 'Kafar Souseh', 'كفرسوسة', ST_SetSRID(ST_MakePoint(36.2750, 33.5020), 4326), true),
('S008', 'Malki', 'المالكي', ST_SetSRID(ST_MakePoint(36.2800, 33.5170), 4326), false),
('S009', 'Abu Rummaneh', 'أبو رمانة', ST_SetSRID(ST_MakePoint(36.2850, 33.5160), 4326), true),
('S010', 'Muhajirin', 'المهاجرين', ST_SetSRID(ST_MakePoint(36.2880, 33.5210), 4326), false),
('S011', 'Saroujah', 'الصالحية', ST_SetSRID(ST_MakePoint(36.3050, 33.5180), 4326), true),
('S012', 'Jisr al-Abyad', 'جسر الأبيض', ST_SetSRID(ST_MakePoint(36.3080, 33.5200), 4326), false),
('S013', 'Abbasiyyin Square', 'ساحة العباسيين', ST_SetSRID(ST_MakePoint(36.3200, 33.5175), 4326), true),
('S014', 'Jobar', 'جوبر', ST_SetSRID(ST_MakePoint(36.3350, 33.5220), 4326), false),
('S015', 'Qaboun', 'القابون', ST_SetSRID(ST_MakePoint(36.3400, 33.5350), 4326), false),
('S016', 'Barzeh', 'برزة', ST_SetSRID(ST_MakePoint(36.3180, 33.5450), 4326), true),
('S017', 'Tishreen Park', 'حديقة تشرين', ST_SetSRID(ST_MakePoint(36.3100, 33.5250), 4326), true),
('S018', 'Damascus University', 'جامعة دمشق', ST_SetSRID(ST_MakePoint(36.2880, 33.5130), 4326), true),
('S019', 'Rawda', 'الروضة', ST_SetSRID(ST_MakePoint(36.2960, 33.5140), 4326), false),
('S020', 'Sha''lan', 'الشعلان', ST_SetSRID(ST_MakePoint(36.2900, 33.5155), 4326), true),
('S021', 'Mazraa', 'المزرعة', ST_SetSRID(ST_MakePoint(36.2830, 33.5030), 4326), false),
('S022', 'Western Bus Station', 'المحطة الغربية (السومرية)', ST_SetSRID(ST_MakePoint(36.2350, 33.5000), 4326), true),
('S023', 'Daraya Junction', 'مفرق داريا', ST_SetSRID(ST_MakePoint(36.2400, 33.4950), 4326), false),
('S024', 'Moadamiyeh', 'المعضمية', ST_SetSRID(ST_MakePoint(36.2200, 33.4800), 4326), true),
('S025', 'Harasta', 'حرستا', ST_SetSRID(ST_MakePoint(36.3550, 33.5500), 4326), true),
('S026', 'Douma Entrance', 'مدخل دوما', ST_SetSRID(ST_MakePoint(36.3800, 33.5600), 4326), true),
('S027', 'Jaramana', 'جرمانا', ST_SetSRID(ST_MakePoint(36.3300, 33.4900), 4326), true),
('S028', 'Sayyidah Zaynab', 'السيدة زينب', ST_SetSRID(ST_MakePoint(36.3400, 33.4500), 4326), true),
('S029', 'Airport Road', 'طريق المطار', ST_SetSRID(ST_MakePoint(36.3500, 33.4700), 4326), false),
('S030', 'Dwel''a', 'الدويلعة', ST_SetSRID(ST_MakePoint(36.3250, 33.4850), 4326), false),
('S031', 'Midan', 'الميدان', ST_SetSRID(ST_MakePoint(36.3000, 33.4950), 4326), true),
('S032', 'Zahira', 'الظاهرة', ST_SetSRID(ST_MakePoint(36.2970, 33.4970), 4326), false),
('S033', 'Bab Touma', 'باب توما', ST_SetSRID(ST_MakePoint(36.3150, 33.5130), 4326), true),
('S034', 'Bab Sharqi', 'باب شرقي', ST_SetSRID(ST_MakePoint(36.3200, 33.5120), 4326), true),
('S035', 'Old City Center', 'وسط المدينة القديمة', ST_SetSRID(ST_MakePoint(36.3100, 33.5110), 4326), true),
('S036', 'Kassaa', 'القصاع', ST_SetSRID(ST_MakePoint(36.3180, 33.5160), 4326), false),
('S037', 'Tijara Center', 'مركز التجارة', ST_SetSRID(ST_MakePoint(36.2950, 33.5100), 4326), true),
('S038', 'Mezze Autostrad West', 'المزة أوتوستراد غرب', ST_SetSRID(ST_MakePoint(36.2500, 33.5030), 4326), false),
('S039', 'Dummar', 'دمر', ST_SetSRID(ST_MakePoint(36.2300, 33.5150), 4326), true),
('S040', 'Qudsaya Entrance', 'مدخل قدسيا', ST_SetSRID(ST_MakePoint(36.2150, 33.5200), 4326), false),
('S041', 'Rabweh', 'الربوة', ST_SetSRID(ST_MakePoint(36.2700, 33.5180), 4326), true),
('S042', 'Muhajireen Heights', 'أعالي المهاجرين', ST_SetSRID(ST_MakePoint(36.2860, 33.5250), 4326), false);

-- ============================================================
-- ROUTES (8 Damascus corridors)
-- ============================================================

INSERT INTO routes (route_id, name, name_ar, route_type, color, distance_km, avg_duration_min, fare_syp) VALUES
('R001', 'Marjeh → Mezzeh Highway', 'المرجة → أوتوستراد المزة', 'bus', '#428177', 8.5, 35, 2000),
('R002', 'Baramkeh → Barzeh', 'البرامكة → برزة', 'bus', '#054239', 12.0, 45, 2500),
('R003', 'Umayyad → Qaboun', 'الأمويين → القابون', 'bus', '#002623', 10.5, 40, 2000),
('R004', 'Old City → Jaramana', 'المدينة القديمة → جرمانا', 'microbus', '#b9a779', 9.0, 35, 3000),
('R005', 'Marjeh → Sayyidah Zaynab', 'المرجة → السيدة زينب', 'bus', '#988561', 18.0, 55, 3500),
('R006', 'Muhajirin → Kafar Souseh', 'المهاجرين → كفرسوسة', 'microbus', '#6b1f2a', 6.5, 25, 2500),
('R007', 'Abbasiyyin → Harasta', 'العباسيين → حرستا', 'bus', '#4a151e', 8.0, 30, 2000),
('R008', 'Mezzeh → Dummar', 'المزة → دمر', 'microbus', '#3d3a3b', 11.0, 40, 3000);

-- ============================================================
-- ROUTE-STOP ASSIGNMENTS
-- ============================================================

-- R001: Marjeh → Mezzeh Highway
INSERT INTO route_stops (route_id, stop_id, stop_sequence, typical_arrival_offset_min) VALUES
((SELECT id FROM routes WHERE route_id='R001'), (SELECT id FROM stops WHERE stop_id='S001'), 1, 0),
((SELECT id FROM routes WHERE route_id='R001'), (SELECT id FROM stops WHERE stop_id='S037'), 2, 5),
((SELECT id FROM routes WHERE route_id='R001'), (SELECT id FROM stops WHERE stop_id='S004'), 3, 10),
((SELECT id FROM routes WHERE route_id='R001'), (SELECT id FROM stops WHERE stop_id='S007'), 4, 18),
((SELECT id FROM routes WHERE route_id='R001'), (SELECT id FROM stops WHERE stop_id='S038'), 5, 25),
((SELECT id FROM routes WHERE route_id='R001'), (SELECT id FROM stops WHERE stop_id='S005'), 6, 30),
((SELECT id FROM routes WHERE route_id='R001'), (SELECT id FROM stops WHERE stop_id='S006'), 7, 35);

-- R002: Baramkeh → Barzeh
INSERT INTO route_stops (route_id, stop_id, stop_sequence, typical_arrival_offset_min) VALUES
((SELECT id FROM routes WHERE route_id='R002'), (SELECT id FROM stops WHERE stop_id='S004'), 1, 0),
((SELECT id FROM routes WHERE route_id='R002'), (SELECT id FROM stops WHERE stop_id='S003'), 2, 8),
((SELECT id FROM routes WHERE route_id='R002'), (SELECT id FROM stops WHERE stop_id='S011'), 3, 15),
((SELECT id FROM routes WHERE route_id='R002'), (SELECT id FROM stops WHERE stop_id='S017'), 4, 22),
((SELECT id FROM routes WHERE route_id='R002'), (SELECT id FROM stops WHERE stop_id='S013'), 5, 30),
((SELECT id FROM routes WHERE route_id='R002'), (SELECT id FROM stops WHERE stop_id='S016'), 6, 40),
((SELECT id FROM routes WHERE route_id='R002'), (SELECT id FROM stops WHERE stop_id='S025'), 7, 45);

-- R003: Umayyad → Qaboun
INSERT INTO route_stops (route_id, stop_id, stop_sequence, typical_arrival_offset_min) VALUES
((SELECT id FROM routes WHERE route_id='R003'), (SELECT id FROM stops WHERE stop_id='S003'), 1, 0),
((SELECT id FROM routes WHERE route_id='R003'), (SELECT id FROM stops WHERE stop_id='S019'), 2, 6),
((SELECT id FROM routes WHERE route_id='R003'), (SELECT id FROM stops WHERE stop_id='S011'), 3, 12),
((SELECT id FROM routes WHERE route_id='R003'), (SELECT id FROM stops WHERE stop_id='S013'), 4, 20),
((SELECT id FROM routes WHERE route_id='R003'), (SELECT id FROM stops WHERE stop_id='S014'), 5, 28),
((SELECT id FROM routes WHERE route_id='R003'), (SELECT id FROM stops WHERE stop_id='S015'), 6, 36),
((SELECT id FROM routes WHERE route_id='R003'), (SELECT id FROM stops WHERE stop_id='S025'), 7, 40);

-- R004: Old City → Jaramana
INSERT INTO route_stops (route_id, stop_id, stop_sequence, typical_arrival_offset_min) VALUES
((SELECT id FROM routes WHERE route_id='R004'), (SELECT id FROM stops WHERE stop_id='S035'), 1, 0),
((SELECT id FROM routes WHERE route_id='R004'), (SELECT id FROM stops WHERE stop_id='S034'), 2, 5),
((SELECT id FROM routes WHERE route_id='R004'), (SELECT id FROM stops WHERE stop_id='S033'), 3, 10),
((SELECT id FROM routes WHERE route_id='R004'), (SELECT id FROM stops WHERE stop_id='S036'), 4, 15),
((SELECT id FROM routes WHERE route_id='R004'), (SELECT id FROM stops WHERE stop_id='S030'), 5, 22),
((SELECT id FROM routes WHERE route_id='R004'), (SELECT id FROM stops WHERE stop_id='S027'), 6, 30),
((SELECT id FROM routes WHERE route_id='R004'), (SELECT id FROM stops WHERE stop_id='S028'), 7, 35);

-- R005: Marjeh → Sayyidah Zaynab
INSERT INTO route_stops (route_id, stop_id, stop_sequence, typical_arrival_offset_min) VALUES
((SELECT id FROM routes WHERE route_id='R005'), (SELECT id FROM stops WHERE stop_id='S001'), 1, 0),
((SELECT id FROM routes WHERE route_id='R005'), (SELECT id FROM stops WHERE stop_id='S031'), 2, 10),
((SELECT id FROM routes WHERE route_id='R005'), (SELECT id FROM stops WHERE stop_id='S032'), 3, 15),
((SELECT id FROM routes WHERE route_id='R005'), (SELECT id FROM stops WHERE stop_id='S030'), 4, 25),
((SELECT id FROM routes WHERE route_id='R005'), (SELECT id FROM stops WHERE stop_id='S027'), 5, 35),
((SELECT id FROM routes WHERE route_id='R005'), (SELECT id FROM stops WHERE stop_id='S029'), 6, 45),
((SELECT id FROM routes WHERE route_id='R005'), (SELECT id FROM stops WHERE stop_id='S028'), 7, 55);

-- R006: Muhajirin → Kafar Souseh
INSERT INTO route_stops (route_id, stop_id, stop_sequence, typical_arrival_offset_min) VALUES
((SELECT id FROM routes WHERE route_id='R006'), (SELECT id FROM stops WHERE stop_id='S010'), 1, 0),
((SELECT id FROM routes WHERE route_id='R006'), (SELECT id FROM stops WHERE stop_id='S009'), 2, 4),
((SELECT id FROM routes WHERE route_id='R006'), (SELECT id FROM stops WHERE stop_id='S008'), 3, 8),
((SELECT id FROM routes WHERE route_id='R006'), (SELECT id FROM stops WHERE stop_id='S020'), 4, 12),
((SELECT id FROM routes WHERE route_id='R006'), (SELECT id FROM stops WHERE stop_id='S018'), 5, 16),
((SELECT id FROM routes WHERE route_id='R006'), (SELECT id FROM stops WHERE stop_id='S021'), 6, 20),
((SELECT id FROM routes WHERE route_id='R006'), (SELECT id FROM stops WHERE stop_id='S007'), 7, 25);

-- R007: Abbasiyyin → Harasta
INSERT INTO route_stops (route_id, stop_id, stop_sequence, typical_arrival_offset_min) VALUES
((SELECT id FROM routes WHERE route_id='R007'), (SELECT id FROM stops WHERE stop_id='S013'), 1, 0),
((SELECT id FROM routes WHERE route_id='R007'), (SELECT id FROM stops WHERE stop_id='S014'), 2, 8),
((SELECT id FROM routes WHERE route_id='R007'), (SELECT id FROM stops WHERE stop_id='S015'), 3, 16),
((SELECT id FROM routes WHERE route_id='R007'), (SELECT id FROM stops WHERE stop_id='S016'), 4, 22),
((SELECT id FROM routes WHERE route_id='R007'), (SELECT id FROM stops WHERE stop_id='S025'), 5, 28),
((SELECT id FROM routes WHERE route_id='R007'), (SELECT id FROM stops WHERE stop_id='S026'), 6, 30);

-- R008: Mezzeh → Dummar
INSERT INTO route_stops (route_id, stop_id, stop_sequence, typical_arrival_offset_min) VALUES
((SELECT id FROM routes WHERE route_id='R008'), (SELECT id FROM stops WHERE stop_id='S005'), 1, 0),
((SELECT id FROM routes WHERE route_id='R008'), (SELECT id FROM stops WHERE stop_id='S038'), 2, 6),
((SELECT id FROM routes WHERE route_id='R008'), (SELECT id FROM stops WHERE stop_id='S041'), 3, 14),
((SELECT id FROM routes WHERE route_id='R008'), (SELECT id FROM stops WHERE stop_id='S039'), 4, 28),
((SELECT id FROM routes WHERE route_id='R008'), (SELECT id FROM stops WHERE stop_id='S040'), 5, 36),
((SELECT id FROM routes WHERE route_id='R008'), (SELECT id FROM stops WHERE stop_id='S022'), 6, 40);

-- ============================================================
-- VEHICLES (24 vehicles across fleet)
-- ============================================================

INSERT INTO vehicles (vehicle_id, name, name_ar, vehicle_type, capacity, status, assigned_route_id) VALUES
-- Buses (12)
('BUS-001', 'Bus Damascus 001', 'باص دمشق 001', 'bus', 45, 'active', (SELECT id FROM routes WHERE route_id='R001')),
('BUS-002', 'Bus Damascus 002', 'باص دمشق 002', 'bus', 45, 'active', (SELECT id FROM routes WHERE route_id='R001')),
('BUS-003', 'Bus Damascus 003', 'باص دمشق 003', 'bus', 45, 'active', (SELECT id FROM routes WHERE route_id='R002')),
('BUS-004', 'Bus Damascus 004', 'باص دمشق 004', 'bus', 45, 'active', (SELECT id FROM routes WHERE route_id='R002')),
('BUS-005', 'Bus Damascus 005', 'باص دمشق 005', 'bus', 45, 'active', (SELECT id FROM routes WHERE route_id='R003')),
('BUS-006', 'Bus Damascus 006', 'باص دمشق 006', 'bus', 45, 'active', (SELECT id FROM routes WHERE route_id='R003')),
('BUS-007', 'Bus Damascus 007', 'باص دمشق 007', 'bus', 45, 'active', (SELECT id FROM routes WHERE route_id='R005')),
('BUS-008', 'Bus Damascus 008', 'باص دمشق 008', 'bus', 45, 'active', (SELECT id FROM routes WHERE route_id='R005')),
('BUS-009', 'Bus Damascus 009', 'باص دمشق 009', 'bus', 45, 'active', (SELECT id FROM routes WHERE route_id='R007')),
('BUS-010', 'Bus Damascus 010', 'باص دمشق 010', 'bus', 45, 'idle', NULL),
('BUS-011', 'Bus Damascus 011', 'باص دمشق 011', 'bus', 45, 'maintenance', NULL),
('BUS-012', 'Bus Damascus 012', 'باص دمشق 012', 'bus', 45, 'idle', NULL),
-- Microbuses (8)
('MIC-001', 'Microbus 001', 'ميكروباص 001', 'microbus', 14, 'active', (SELECT id FROM routes WHERE route_id='R004')),
('MIC-002', 'Microbus 002', 'ميكروباص 002', 'microbus', 14, 'active', (SELECT id FROM routes WHERE route_id='R004')),
('MIC-003', 'Microbus 003', 'ميكروباص 003', 'microbus', 14, 'active', (SELECT id FROM routes WHERE route_id='R006')),
('MIC-004', 'Microbus 004', 'ميكروباص 004', 'microbus', 14, 'active', (SELECT id FROM routes WHERE route_id='R006')),
('MIC-005', 'Microbus 005', 'ميكروباص 005', 'microbus', 14, 'active', (SELECT id FROM routes WHERE route_id='R008')),
('MIC-006', 'Microbus 006', 'ميكروباص 006', 'microbus', 14, 'active', (SELECT id FROM routes WHERE route_id='R008')),
('MIC-007', 'Microbus 007', 'ميكروباص 007', 'microbus', 14, 'idle', NULL),
('MIC-008', 'Microbus 008', 'ميكروباص 008', 'microbus', 14, 'idle', NULL),
-- Taxis (4)
('TAX-001', 'Taxi 001', 'تاكسي 001', 'taxi', 4, 'active', NULL),
('TAX-002', 'Taxi 002', 'تاكسي 002', 'taxi', 4, 'active', NULL),
('TAX-003', 'Taxi 003', 'تاكسي 003', 'taxi', 4, 'active', NULL),
('TAX-004', 'Taxi 004', 'تاكسي 004', 'taxi', 4, 'idle', NULL);

-- ============================================================
-- SCHEDULES (daily service)
-- ============================================================

-- Weekdays (Sunday=0 to Thursday=4 in Syria)
INSERT INTO schedules (route_id, day_of_week, first_departure, last_departure, frequency_min)
SELECT r.id, d.dow, '05:30'::TIME, '23:00'::TIME,
    CASE r.route_type
        WHEN 'bus' THEN 12
        WHEN 'microbus' THEN 8
        ELSE 15
    END
FROM routes r
CROSS JOIN (VALUES (0),(1),(2),(3),(4)) AS d(dow)
WHERE r.is_active = true;

-- Friday & Saturday (reduced service)
INSERT INTO schedules (route_id, day_of_week, first_departure, last_departure, frequency_min)
SELECT r.id, d.dow, '06:00'::TIME, '22:00'::TIME,
    CASE r.route_type
        WHEN 'bus' THEN 20
        WHEN 'microbus' THEN 12
        ELSE 20
    END
FROM routes r
CROSS JOIN (VALUES (5),(6)) AS d(dow)
WHERE r.is_active = true;

-- ============================================================
-- GEOFENCES (key zones)
-- ============================================================

INSERT INTO geofences (name, name_ar, geometry, geofence_type, speed_limit_kmh) VALUES
('Damascus City Center', 'وسط مدينة دمشق',
    ST_SetSRID(ST_GeomFromText('POLYGON((36.295 33.505, 36.325 33.505, 36.325 33.525, 36.295 33.525, 36.295 33.505))'), 4326),
    'zone', 30),
('Western Bus Station', 'محطة السومرية',
    ST_SetSRID(ST_GeomFromText('POLYGON((36.230 33.496, 36.240 33.496, 36.240 33.504, 36.230 33.504, 36.230 33.496))'), 4326),
    'terminal', 20),
('Old City Zone', 'منطقة المدينة القديمة',
    ST_SetSRID(ST_GeomFromText('POLYGON((36.305 33.508, 36.322 33.508, 36.322 33.516, 36.305 33.516, 36.305 33.508))'), 4326),
    'zone', 20);
