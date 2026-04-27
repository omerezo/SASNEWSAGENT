/**
 * Test agent — posts a sample bilingual news article to /api/agent/news
 *
 * Usage:
 *   1. Copy your API key from Admin → Settings → Agent API Key
 *   2. Set it in API_KEY below (or export AGENT_KEY=<key> in your shell)
 *   3. node test-agent.mjs
 */

const BASE_URL = process.env.AGENT_BASE_URL || 'https://sas-academy.up.railway.app';
const API_KEY  = process.env.AGENT_KEY       || 'sas-agent-b27bdbe6-2496-4a58-93cf-8d6b5a5e0de1';

const newsPayload = {
  title_ar:   'أكاديمية سوداني تحقق إنجازاً رياضياً بارزاً في بطولة المنطقة',
  title_en:   'Sudani Academy Achieves Outstanding Sports Milestone at Regional Championship',

  content_ar: `حققت أكاديمية سوداني للرياضة إنجازاً رياضياً لافتاً خلال بطولة المنطقة الأخيرة، إذ أبلى لاعبوها البلاء الحسن وأثبتوا جدارتهم على أرض الملعب.

تمكّن الفريق من الفوز بثلاث ميداليات ذهبية وميداليتَين فضيتَين، في نتيجة تعكس مستوى التدريب الرفيع الذي يتلقاه الرياضيون على يد كوادر متخصصة.

صرّح مدير الأكاديمية بأن هذا الإنجاز ثمرة لسنوات من العمل الدؤوب والتخطيط المحكم، مؤكداً أن الأكاديمية ستواصل مسيرتها نحو تطوير الكفاءات الرياضية الواعدة وإعداد أبطال المستقبل.`,

  content_en: `Sudani Academy Sport has achieved a remarkable milestone at the latest Regional Championship, with its athletes delivering outstanding performances and proving their caliber on the field.

The team secured three gold medals and two silver medals — results that reflect the high standard of coaching provided by the academy's specialized staff.

The academy's director stated that this achievement is the fruit of years of dedicated work and meticulous planning, affirming that the academy will continue its journey toward developing promising athletic talents and preparing future champions.`,

  excerpt_ar: 'فوز بثلاث ميداليات ذهبية وميداليتَين فضيتَين في بطولة المنطقة الرياضية الأخيرة.',
  excerpt_en: 'Three gold medals and two silver medals won at the latest Regional Sports Championship.',

  // Public image — replace with any accessible URL or a data:image/jpeg;base64,... string
  image: 'https://images.unsplash.com/photo-1517649763962-0c623066013b?w=1200&q=80',

  featured:  false,
  published: true,
};

async function postNews() {
  if (API_KEY === 'PASTE_YOUR_KEY_HERE') {
    console.error('ERROR: Set your API key in API_KEY or export AGENT_KEY=<key>');
    process.exit(1);
  }

  console.log(`Posting news to ${BASE_URL}/api/agent/news ...`);

  const res = await fetch(`${BASE_URL}/api/agent/news`, {
    method:  'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Agent-Key':  API_KEY,
    },
    body: JSON.stringify(newsPayload),
  });

  const data = await res.json();

  if (res.ok && data.success) {
    console.log('SUCCESS');
    console.log('  News ID :', data.id);
    console.log('  View at :', `${BASE_URL}/news`);
  } else {
    console.error('FAILED — HTTP', res.status);
    console.error('  Response:', JSON.stringify(data, null, 2));
    process.exit(1);
  }
}

postNews().catch(err => { console.error('Unexpected error:', err); process.exit(1); });
