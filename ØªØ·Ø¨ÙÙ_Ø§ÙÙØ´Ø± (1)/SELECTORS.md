# المحددات ومسارات القراءة والنشر

الملف `config/selectors.yaml` هو نقطة تعديل محددات المنصات ومسارات النشر. محددات المواقع تتغير دون سابق إنذار؛ النسخة المرفقة نقطة بدء قابلة للاختبار وليست ضمانًا لثبات الواجهات.

## بنية المنصة

```yaml
platforms:
  x:
    session_url: https://x.com/home
    session_valid: 'selector-for-logged-in-state'
    login_required: 'selector-for-login-form'
    source:
      item: 'article[data-testid="tweet"]'
      text: '[data-testid="tweetText"]'
      link: 'a[href*="/status/"]'
      image: 'img:not([src*="profile_images"])'
      video: 'video'
    publish:
      start_url: https://x.com/compose/post
      success: 'selector-for-real-success-confirmation'
      steps: []
```

- `session_valid` و`login_required`: يستخدمان في فحص الجلسة. عدم ظهور أي منهما يعطي `unknown` وليس نجاحًا.
- `source.item`: العنصر المتكرر لكل منشور في صفحة المصدر.
- `text`, `link`, `image`, `video`: محددات نسبية داخل العنصر.
- `publish.steps`: خطوات Playwright متسلسلة.
- `publish.success`: لا يُعتبر النشر ناجحًا إلا إذا ظهر هذا المؤشر بعد الخطوات.

## إجراءات النشر المدعومة

```yaml
steps:
  - {action: goto, value: 'https://example.com/compose'}
  - {action: wait_for, selector: 'textarea'}
  - {action: fill, selector: 'textarea', value: '{text}'}
  - {action: upload, selector: 'input[type="file"]', if_media: true, required: true}
  - {action: click, selector: 'button:has-text("نشر")'}
  - {action: press, selector: 'textarea', value: 'Enter'}
  - {action: wait, seconds: 2, optional: true}
```

| الإجراء | الوظيفة |
|---|---|
| `goto` | فتح عنوان؛ يدعم `{target_url}` لـTelegram |
| `fill` | انتظار الحقل ثم تعبئته بـ`{text}` |
| `upload` | رفع الملفات المعالجة أو المحلية |
| `click` | الضغط على أول عنصر مطابق |
| `press` | إرسال مفتاح للعنصر |
| `wait_for` | انتظار ظهور عنصر |
| `wait` | انتظار محدود حتى 30 ثانية |

- `if_media: true`: تتخطى الخطوة إذا لا توجد وسائط.
- `optional: true`: يسمح بفشل الخطوة بعد محاولتها. لا تجعل خطوة النشر الأساسية اختيارية.
- `{text}` هو النص النهائي بعد المراجعة، و`{target_url}` هو رابط محادثة Telegram.

يدعم Playwright محددات CSS ومحدداته الخاصة مثل `role=button[name=…]` و`:has-text(…)`. استخدم أقل محدد هشّ ممكن، ويفضل سمات `data-testid` أو الأدوار والأسماء المستقرة على ترتيب `div`.

## تجاوز محددات مصدر واحد

يمكن أن يحتوي `source.config` على قيم قراءة خاصة بالمصدر دون تغيير بقية المصادر. استخدمه للتجربة على مصدر واحد قبل تعميم التعديل. احتفظ بنسخة من YAML قبل التعديل.

## أمان النتيجة

- إذا لم يوجد `success` يصبح الناتج `publish_unknown` بعد تنفيذ الخطوات.
- إذا لم يظهر `success` خلال المهلة يصبح الناتج `publish_unknown`.
- أي توقف بعد بدء مسار النشر يُعامل أيضًا كنتيجة غير مؤكدة، لأن المنصة قد تكون استلمت المحتوى.
- لا تُعاد مهمة النشر تلقائيًا. افتح المنصة وتحقق، ثم سجّل النتيجة من صفحة المراجعة.

Telegram مرفق بلا `success` افتراضيًا لأن Toast موحدًا موثوقًا غير متوفر. لا تضف مؤشرًا عامًا قد يظهر قبل النشر الحقيقي فقط لإخفاء حالة الغموض.

## طريقة تحديث محدد بأمان

1. أبقِ `DRY_RUN=true` أثناء تجهيز النصوص والوسائط.
2. افتح المنصة يدويًا وافحص DOM أو استخدم Playwright locator في بيئة اختبار.
3. عدّل مصدرًا واحدًا أو منصة واحدة فقط.
4. اختبر **فحص الجلسة** أولًا، ثم قراءة مصدر واحد.
5. راجع النص والروابط والوسائط المكتشفة؛ لا تختبر النشر على محتوى حقيقي مهم.
6. عند الحاجة لاختبار النشر الفعلي استخدم محتوى تجريبيًا مملوكًا لك وتأكد يدويًا من النتيجة.
7. وثّق تاريخ التغيير والمحدد الذي تعطل.

## تنبيه

لا تجعل نجاح الضغط على زر «نشر» دليلًا على اكتمال العملية. الدليل يجب أن يكون رسالة نجاح حقيقية أو رابط المنشور أو حالة واجهة لا تظهر إلا بعد النشر. إن لم يمكن تحقيق ذلك، فالأصح إبقاء النتيجة غير مؤكدة.
