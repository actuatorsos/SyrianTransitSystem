/**
 * Tests for passenger app route search and Arabic text normalization.
 * Covers: DAM-192
 *
 * Run with: node tests/test_passenger_search.js
 */

'use strict';

// ─── Extracted from public/passenger/index.html (lines 302–323) ───

function normalizeArabic(text) {
  return text
    // Remove tashkeel (harakat, shadda, etc.)
    .replace(/[\u0610-\u061A\u064B-\u065F\u0670]/g, '')
    // Normalize alef forms (أ إ آ ٱ) → ا
    .replace(/[\u0622\u0623\u0625\u0671]/g, '\u0627')
    // Normalize teh marbuta (ة) → ه
    .replace(/\u0629/g, '\u0647')
    // Normalize alef maqsura (ى) → ي
    .replace(/\u0649/g, '\u064A')
    .toLowerCase()
    .trim();
}

function matchesSearch(route, query) {
  if (!query) return true;
  const q = normalizeArabic(query);
  return (
    normalizeArabic(route.name).includes(q) ||
    normalizeArabic(route.nameAr).includes(q)
  );
}

// ─── Route data (from public/passenger/index.html lines 262–271) ───
const ROUTES = [
  { id: "marjeh_western",    name: "Marjeh → Western Station",  nameAr: "المرجة → المحطة الغربية" },
  { id: "mezzeh_autostrade", name: "Mezzeh Autostrade",          nameAr: "أوتوستراد المزة" },
  { id: "harasta",           name: "Harasta → Damascus",         nameAr: "حرستا → دمشق" },
  { id: "douma",             name: "Douma → Damascus",           nameAr: "دوما → دمشق" },
  { id: "jaramana",          name: "Jaramana → Center",          nameAr: "جرمانا → المركز" },
  { id: "qudsaya",           name: "Qudsaya → Damascus",         nameAr: "قدسيا → دمشق" },
  { id: "airport",           name: "Airport Road",               nameAr: "طريق المطار" },
  { id: "barzeh",            name: "Barzeh → Center",            nameAr: "برزة → المركز" },
];

// ─── Test harness ───
let passed = 0;
let failed = 0;

function assert(description, condition) {
  if (condition) {
    console.log(`  ✓ ${description}`);
    passed++;
  } else {
    console.error(`  ✗ FAIL: ${description}`);
    failed++;
  }
}

function section(title) {
  console.log(`\n── ${title} ──`);
}

// ─── 1. normalizeArabic: tashkeel removal ───
section('normalizeArabic — tashkeel (diacritics) removal');
assert(
  'removes fatha (U+064E)',
  normalizeArabic('مَرجة') === normalizeArabic('مرجة')
);
assert(
  'removes kasra (U+0650)',
  normalizeArabic('دِمشق') === normalizeArabic('دمشق')
);
assert(
  'removes damma (U+064F)',
  normalizeArabic('بُرزة') === normalizeArabic('برزة')
);
assert(
  'removes shadda (U+0651)',
  normalizeArabic('المرجَّة') === normalizeArabic('المرجة')
);
assert(
  'removes tanwin fath (U+064B)',
  normalizeArabic('خطاً') === normalizeArabic('خطا')
);
assert(
  'removes superscript alef (U+0670)',
  normalizeArabic('ذَٰلك') === normalizeArabic('ذلك')
);
assert(
  'fully diacriticized word matches plain form',
  normalizeArabic('أَوْتُوسْتِرَاد') === normalizeArabic('أوتوستراد')
);

// ─── 2. normalizeArabic: alef variant normalization ───
section('normalizeArabic — alef variants → ا');
assert(
  'alef with hamza above (أ U+0623) → ا',
  normalizeArabic('أوتوستراد').startsWith('ا')
);
assert(
  'alef with hamza below (إ U+0625) → ا',
  normalizeArabic('إنسان') === normalizeArabic('انسان')
);
assert(
  'alef with madda (آ U+0622) → ا',
  normalizeArabic('آخر') === normalizeArabic('اخر')
);
assert(
  'alef wasla (ٱ U+0671) → ا',
  normalizeArabic('ٱلمرجة') === normalizeArabic('المرجة')
);
assert(
  'all alef variants normalize to same value',
  normalizeArabic('أ') === normalizeArabic('إ') &&
  normalizeArabic('إ') === normalizeArabic('آ') &&
  normalizeArabic('آ') === normalizeArabic('ا')
);

// ─── 3. normalizeArabic: teh marbuta normalization ───
section('normalizeArabic — teh marbuta (ة) → ه');
assert(
  'teh marbuta (ة U+0629) normalizes to ha (ه U+0647)',
  normalizeArabic('المرجة') === normalizeArabic('المرجه')
);
assert(
  'محطة matches محطه',
  normalizeArabic('محطة') === normalizeArabic('محطه')
);
assert(
  'الغربية ends in يه after normalization (ة → ه)',
  normalizeArabic('الغربية').endsWith('يه') === true  // ة → ه
);

// ─── 4. normalizeArabic: alef maqsura normalization ───
section('normalizeArabic — alef maqsura (ى) → ي');
assert(
  'alef maqsura (ى U+0649) normalizes to ya (ي U+064A)',
  normalizeArabic('المزى') === normalizeArabic('المزي')
);
assert(
  'على matches علي',
  normalizeArabic('على') === normalizeArabic('علي')
);

// ─── 5. normalizeArabic: lowercase + trim ───
section('normalizeArabic — lowercase and trim');
assert(
  'converts to lowercase',
  normalizeArabic('Airport') === 'airport'
);
assert(
  'trims leading/trailing whitespace',
  normalizeArabic('  مرجة  ') === 'مرجه'  // teh marbuta also normalized
);
assert(
  'handles mixed Arabic/English',
  normalizeArabic('Marjeh المرجة') === 'marjeh المرجه'
);

// ─── 6. matchesSearch: empty/null query ───
section('matchesSearch — empty query returns all routes');
assert(
  'empty string returns true for all routes',
  ROUTES.every(r => matchesSearch(r, ''))
);
assert(
  'null/undefined query — empty string treated as truthy false',
  matchesSearch(ROUTES[0], null) === true  // if (!query) return true
);

// ─── 7. matchesSearch: English name search ───
section('matchesSearch — English route name search');
assert(
  '"Marjeh" matches Marjeh → Western Station',
  matchesSearch(ROUTES[0], 'Marjeh')
);
assert(
  '"marjeh" (lowercase) matches Marjeh → Western Station',
  matchesSearch(ROUTES[0], 'marjeh')
);
assert(
  '"AIRPORT" (uppercase) matches Airport Road',
  matchesSearch(ROUTES[6], 'AIRPORT')
);
assert(
  '"Western" matches Marjeh → Western Station',
  matchesSearch(ROUTES[0], 'Western')
);
assert(
  '"damascus" matches Harasta → Damascus',
  matchesSearch(ROUTES[2], 'damascus')
);
assert(
  '"barzeh" does NOT match Airport Road',
  !matchesSearch(ROUTES[6], 'barzeh')
);
assert(
  '"autostrade" partial match works',
  matchesSearch(ROUTES[1], 'auto')
);

// ─── 8. matchesSearch: Arabic name search ───
section('matchesSearch — Arabic route name search');
assert(
  '"حرستا" matches Harasta → Damascus',
  matchesSearch(ROUTES[2], 'حرستا')
);
assert(
  '"دمشق" matches multiple Damascus-bound routes',
  ['harasta','douma','qudsaya'].every(id => {
    const r = ROUTES.find(x => x.id === id);
    return matchesSearch(r, 'دمشق');
  })
);
assert(
  '"مطار" matches Airport Road (partial Arabic match)',
  matchesSearch(ROUTES[6], 'مطار')
);
assert(
  '"برزة" matches Barzeh → Center',
  matchesSearch(ROUTES[7], 'برزة')
);
assert(
  '"جرمانا" matches Jaramana → Center',
  matchesSearch(ROUTES[4], 'جرمانا')
);

// ─── 9. matchesSearch: Arabic normalization applied in search ───
section('matchesSearch — normalization applied in Arabic search');
assert(
  '"مرجه" (ha instead of teh marbuta) still matches المرجة route',
  matchesSearch(ROUTES[0], 'مرجه')
);
assert(
  '"اوتوستراد" (no hamza on alef) still matches أوتوستراد المزة',
  matchesSearch(ROUTES[1], 'اوتوستراد')
);
assert(
  '"المحطه الغربيه" (ha instead of teh marbuta) matches المحطة الغربية',
  matchesSearch(ROUTES[0], 'المحطه')
);
assert(
  'Fully diacriticized Arabic query matches undiacriticized route name',
  matchesSearch(ROUTES[2], 'حَرَسْتَا')
);
assert(
  '"قُدْسَيَا" with tashkeel matches قدسيا route',
  matchesSearch(ROUTES[5], 'قُدْسَيَا')
);

// ─── 10. filterRoutes simulation: real-time filtering ───
section('filterRoutes simulation — real-time filtering behavior');

function filterRoutes(query) {
  return ROUTES.filter(r => matchesSearch(r, query));
}

assert(
  'empty query returns all 8 routes',
  filterRoutes('').length === 8
);
assert(
  '"Damascus" returns 3 routes (Harasta, Douma, Qudsaya)',
  filterRoutes('Damascus').length === 3
);
assert(
  '"دمشق" also returns 3 routes',
  filterRoutes('دمشق').length === 3
);
assert(
  '"Airport" returns exactly 1 route',
  filterRoutes('Airport').length === 1 && filterRoutes('Airport')[0].id === 'airport'
);
assert(
  '"مطار" returns exactly 1 route (Arabic search)',
  filterRoutes('مطار').length === 1 && filterRoutes('مطار')[0].id === 'airport'
);
assert(
  '"xyz_no_match" returns 0 routes',
  filterRoutes('xyz_no_match').length === 0
);
assert(
  '"center" returns 2 routes (Jaramana → Center, Barzeh → Center)',
  filterRoutes('center').length === 2
);
assert(
  'Partial match "arast" matches only Harasta',
  filterRoutes('arast').length === 1 && filterRoutes('arast')[0].id === 'harasta'
);

// ─── 11. Clear/reset behavior ───
section('Clear/reset — empty string resets to full list');
assert(
  'Filtering then clearing returns all routes',
  (() => {
    const afterFilter = filterRoutes('Airport');
    const afterClear = filterRoutes('');
    return afterFilter.length === 1 && afterClear.length === 8;
  })()
);
assert(
  'Whitespace-only query returns all routes (after trim)',
  filterRoutes('   ').length === 8
);

// ─── 12. Edge cases ───
section('Edge cases');
assert(
  'Route with no nameAr would not crash — nameAr always defined in ROUTES',
  ROUTES.every(r => typeof r.nameAr === 'string')
);
assert(
  'normalizeArabic on empty string returns empty string',
  normalizeArabic('') === ''
);
assert(
  'normalizeArabic on ASCII-only string returns lowercased string',
  normalizeArabic('Airport Road') === 'airport road'
);
assert(
  'Mixed teh marbuta + alef + tashkeel all normalized together',
  normalizeArabic('أُوتُوسْتِرَادُ المُزَّةِ') === normalizeArabic('اوتوستراد المزه')
);

// ─── Summary ───
console.log(`\n${'─'.repeat(50)}`);
console.log(`Results: ${passed} passed, ${failed} failed out of ${passed + failed} tests`);
if (failed === 0) {
  console.log('All tests passed ✓');
  process.exit(0);
} else {
  console.error(`${failed} test(s) FAILED`);
  process.exit(1);
}
