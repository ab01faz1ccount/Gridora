# Persian copy review (Review 5, order 4)

Reviewed by Agent 2 as a newcomer would read it: someone who has used a spreadsheet but never a "data tool", who sees
the text in a side panel, and who must understand **what will happen** without asking anyone. 121 strings were
rewritten (106 distinct rewrites); the rest were already fine. The full catalog is `src/gridora_dataops/i18n/fa.json`.

## Rules I applied
1. **Say what happens, then what to do.** Every error now says what is wrong and the next step ("... اول خطاها را درست کنید.").
2. **No developer words.** Removed: پارامتر, آرگومان, تابع, عملگر, نویسه, هدف, خط‌لوله, ذخیره‌سازی, کلید, متمایز, ساختاریافته,
   عبارت منظم. Kept only words a spreadsheet user knows (ستون، ردیف، فرمول، جدول محوری).
3. **One word per idea**, taken from the web app's own strings (`apps/web/src/i18n/fa.json`) and `docs/UX_SPEC.md`:
   **برگه** (not شیت), **واگرد** (undo), **جدول داده** (Data Table), **کار** (an operation, as in "این کار ..."),
   **ردیف/ستون**, **خانه** (not سلول; see the open question below), **محدوده** (a selected range).
4. **Active, short sentences**, no passive "اعمال می‌شود / پشتیبانی می‌شود" where a plain verb works.
5. **Left/right words avoided** in an RTL interface: "چند حرف از چپ" became "از ابتدای متن".
6. **Digits:** examples and the "N rows" templates use Persian digits by default; the caller can ask for Latin digits.
7. **`too_large_for_history`** uses the exact sentence from UX_SPEC F4.
8. Technical hints are explained when they must stay: the date pattern now says what `%d/%m/%Y` means.

## Terms I am not sure about (decide, do not guess)
| Term | What I used | Why unsure | Who decides |
|---|---|---|---|
| cell | **خانه** | Excel's Persian UI says «سلول»; «خانه» is shorter and plainer, but a user may search for «سلول» | product owner |
| range | **محدوده** | alternatives «بازه», «ناحیه»; «محدوده» matches Excel | product owner |
| Data Table | **جدول داده** | taken from UX_SPEC F4; the web app has «جدول داده‌ها» | Agent 3 / owner |
| ascending / descending | **صعودی / نزولی** + a hint in brackets («کوچک به بزرگ، الف تا ی») | the words alone are not obvious to a newcomer | owner |
| pivot | **جدول محوری (پیوت)** | Excel users know it; a newcomer may not; the keywords include «مقایسه ماه‌ها», «گزارش جدولی» | owner |
| `owner_unknown` | «این جدول به حساب شما وصل نیست.» | internal error; the right words depend on what the screen can do next | Agent 3 |
| «کار» vs «عملیات» | **کار** in messages; labels keep their own nouns | UX_SPEC mixes "operation/کار" | owner |
| Latin letters in options | «حروف انگلیسی» (not «لاتین») | «لاتین» is correct but less common in speech | owner |

## What I could not verify
No real newcomer read these. They are my judgment against the rules above; a 5-minute read-aloud test with two people who have
never used the app would catch what I cannot. The effect sentences ("۱۲ ردیف حذف می‌شود") follow UX_SPEC F3.

## Every rewrite (before -> after)
| Key | Before | After |
|---|---|---|
| `errors: chart_series_mismatch` | سری‌های نمودار باید دسته‌بندی یکسانی داشته باشند. | همه‌ی ستون‌های نمودار باید دسته‌بندی یکسانی داشته باشند. |
| `errors: chart_too_many_categories` | تعداد دسته‌های نمودار بیش از حد مجاز است. | نمودار بیش از حد دسته دارد؛ ستون دیگری برای دسته‌بندی انتخاب کنید یا اول داده را خلاصه کنید. |
| `errors: invalid_param` | مقدار پارامتر نامعتبر است. | یکی از گزینه‌ها مقدار درستی ندارد؛ آن را بررسی کنید. |
| `errors: mixed_column_types` | ستون شامل انواع مختلف داده (مثلاً عدد و متن) است. | این ستون هم عدد دارد هم متن (یا نوع‌های دیگر). اول همه‌ی خانه‌ها را به یک نوع تبدیل کنید. |
| `errors: not_implemented` | این قابلیت هنوز پیاده‌سازی نشده است. | این امکان هنوز آماده نیست. |
| `errors: owner_unknown` | مالک جدول مشخص نیست. | این جدول به حساب شما وصل نیست. |
| `errors: pipeline_aborted` | اجرای خط‌لوله متوقف شد؛ هیچ تغییری اعمال نشد. | اجرای مرحله‌ها متوقف شد؛ هیچ تغییری اعمال نشد. |
| `errors: range_has_error_values` | محدوده شامل مقدارهای خطا (مانند #N/A) است و این عملیات هنوز آن‌ها را پشتیبانی نمی‌کند. | در این محدوده خطا (مثل #N/A) هست و این کار هنوز با آن‌ها کار نمی‌کند. اول خطاها را درست کنید. |
| `errors: range_has_formulas` | محدوده شامل فرمول است و این عملیات فرمول‌ها را به مقدار تبدیل می‌کند. ابتدا تبدیل فرمول‌ها به مقدار را تأیید کنید. | این محدوده فرمول دارد و این کار فرمول‌ها را به مقدار ثابت تبدیل می‌کند. اگر موافقید، گزینه‌ی «فرمول‌ها به مقدار تبدیل شوند» را انتخاب کنید؛ با «واگرد» فرمول‌ها برمی‌گردند. |
| `errors: result_too_large` | نتیجه از حد مجاز بزرگ‌تر است. | نتیجه خیلی بزرگ می‌شود و ساخته نمی‌شود. شرط‌ها را دقیق‌تر کنید یا داده‌ی کمتری انتخاب کنید. |
| `errors: rollback_incomplete` | بازگرداندن گام‌های قبلی کامل انجام نشد؛ داده‌ها را بررسی کنید و از تاریخچه استفاده کنید. | برگرداندن مرحله‌های قبلی کامل نشد. داده‌ها را بررسی کنید و در صورت نیاز از «واگرد» استفاده کنید. |
| `errors: too_large_for_history` | حجم تغییر بیش از حد مجاز برای ثبت در تاریخچه است. | این کار روی کل برگه خیلی بزرگ است و واگرد ندارد. می‌توانید آن را به «جدول داده» تبدیل کنید و آنجا انجام دهید. |
| `errors: type_mismatch` | نوع مقدار یا عملگر با نوع ستون سازگار نیست. | این شرط یا گزینه با نوع ستون جور نیست (مثلاً عدد با متن مقایسه شده است). |
| `errors: unknown_column` | ستونی با این نام در داده‌ها وجود ندارد. | در این داده ستونی با این نام نیست؛ نام ستون را بررسی کنید. |
| `errors: unknown_operation` | این عملیات شناخته‌شده نیست. | این کار شناخته نمی‌شود. |
| `errors: unknown_param` | این پارامتر شناخته‌شده نیست. | این گزینه برای این کار وجود ندارد. |
| `errors: unsupported_target` | این عملیات روی این نوع هدف قابل اجرا نیست. | این کار را نمی‌شود روی این نوع داده (جدول یا محدوده‌ی برگه) انجام داد. |
| `errors: validation_failed` | پارامترهای عملیات نامعتبر است. | گزینه‌های این کار درست پر نشده‌اند؛ پیام کنار هر گزینه را ببینید. |
| `errors: version_conflict` | این نسخه از جدول قبلاً ساخته شده است؛ نسخه‌ها تغییرناپذیرند. | هم‌زمان تغییر دیگری روی این جدول ثبت شد. صفحه را تازه کنید و دوباره امتحان کنید. |
| `errors: version_unavailable` | این نسخه از جدول دیگر در دسترس نیست. | این نسخه‌ی جدول دیگر نگه داشته نشده است. |
| `errors: would_overwrite` | اجرای این عملیات سلول‌های غیرخالیِ بیرون از محدوده را بازنویسی می‌کند. | نتیجه جای بیشتری لازم دارد و کنار محدوده‌ی شما خانه‌ی پر هست. چند ستون یا ردیف خالیِ کنار محدوده باز کنید و دوباره امتحان کنید. |
| `categories.reshape` | بازچینی | تغییر شکل جدول |
| `change_type.description` | نوع یک ستون را تغییر می‌دهد (مثلاً متن به عدد). ارقام فارسی و عربی و جداکننده‌های هزارگان شناخته می‌شوند. | نوع یک ستون را عوض می‌کند (مثلاً متن به عدد). ارقام فارسی و عربی و علامت هزارگان (مثل ٬) شناخته می‌شوند. |
| `change_type.params.date_format.title` | قالب تاریخ (اختیاری، مثل %Y-%m-%d) | الگوی تاریخ (اختیاری؛ مثلاً %d/%m/%Y یعنی روز/ماه/سال) |
| `change_type.params.decimal_separator.title` | جداکننده اعشار در متن | علامت اعشار در متن |
| `change_type.params.formulas.options.refuse` (+9 same) | عملیات متوقف شود (پیش‌فرض) | کار متوقف شود (پیش‌فرض) |
| `change_type.params.on_error.options.fail` (+1 same) | عملیات متوقف شود | کار متوقف شود |
| `change_type.params.to.options.decimal` | عدد دقیق (decimal) | عدد اعشاری دقیق (برای مبلغ) |
| `clean_text.description` | فاصله‌های اضافه، حروف بزرگ و کوچک، و نویسه‌های فارسی و عربی را مرتب می‌کند. هر گزینه‌ی فارسی فقط در صورت انتخاب شما اعمال می‌شود. | فاصله‌های اضافه، حروف بزرگ و کوچک و حرف‌های فارسی و عربی را مرتب می‌کند. هر گزینه‌ی فارسی فقط وقتی اعمال می‌شود که خودتان انتخابش کنید. |
| `clean_text.params.arabic_letters_to_persian.title` | تبدیل حروف عربی هم‌شکل به حروف فارسی (ی و ک) | «ی» و «ک» عربی به فارسی تبدیل شود |
| `clean_text.params.case.title` | حروف لاتین | حروف انگلیسی |
| `clean_text.params.nbsp_to_space.title` | تبدیل فاصله‌ی ناشکن به فاصله‌ی معمولی | فاصله‌های نامرئی (مثل فاصله‌ی ناشکن) به فاصله‌ی معمولی تبدیل شوند |
| `computed_column.defs.Call.args.items.title` | آرگومان | ورودی |
| `computed_column.defs.Call.args.title` | آرگومان‌ها | ورودی‌ها |
| `computed_column.defs.Call.fn.options.concat` | چسباندن متن | چسباندن متن‌ها به هم |
| `computed_column.defs.Call.fn.options.left` | چند نویسه از چپ | چند حرف از ابتدای متن |
| `computed_column.defs.Call.fn.options.len` | تعداد نویسه | تعداد حرف‌ها |
| `computed_column.defs.Call.fn.options.lower` | حروف کوچک لاتین | حروف انگلیسی کوچک |
| `computed_column.defs.Call.fn.options.mod` | باقی‌مانده | باقی‌مانده‌ی تقسیم |
| `computed_column.defs.Call.fn.options.neg` | قرینه | منفی کردن |
| `computed_column.defs.Call.fn.options.not` | نقیض | برعکس (نه) |
| `computed_column.defs.Call.fn.options.right` | چند نویسه از راست | چند حرف از انتهای متن |
| `computed_column.defs.Call.fn.options.round` | گرد به نزدیک‌ترین عدد صحیح | گرد کردن به عدد صحیح |
| `computed_column.defs.Call.fn.options.substring` | زیرمتن (شروع از ۱) | بخشی از متن (شروع از حرف ۱) |
| `computed_column.defs.Call.fn.options.upper` | حروف بزرگ لاتین | حروف انگلیسی بزرگ |
| `computed_column.defs.Call.fn.title` | تابع | چه عملی |
| `computed_column.defs.Call.title` | تابع | عمل |
| `computed_column.defs.Lit.title` | مقدار ثابت | عدد یا متن ثابت |
| `computed_column.description` | یک ستون جدید از روی یک عبارت می‌سازد (حساب، متن، شرط). عبارت ساختاریافته است و هیچ کدی اجرا نمی‌شود. | یک ستون جدید از روی یک محاسبه می‌سازد (حساب، متن، شرط). فقط محاسبه‌هایی که از فهرست آماده انتخاب می‌کنید انجام می‌شود؛ هیچ برنامه‌ای اجرا نمی‌شود. |
| `computed_column.params.expr.title` | عبارت | محاسبه |
| `convert_calendar.description` | تاریخ میلادی را به شمسی یا برعکس تبدیل می‌کند. ذخیره‌سازی همیشه میلادی می‌ماند و هیچ تبدیلی بدون درخواست شما انجام نمی‌شود. سال‌های شمسی ۱۳۰۰ تا ۱۵۰۰ پشتیبانی می‌شود. | تاریخ میلادی را به شمسی یا برعکس تبدیل می‌کند. داده‌ی اصلی همیشه میلادی می‌ماند و هیچ تبدیلی بدون درخواست شما انجام نمی‌شود. سال‌های شمسی ۱۳۰۰ تا ۱۵۰۰ پشتیبانی می‌شود. |
| `convert_calendar.params.direction.title` | جهت تبدیل | تبدیل از کدام به کدام |
| `convert_calendar.params.format.title` | قالب خروجی شمسی | نمایش تاریخ شمسی |
| `filter.defs.Condition.case_sensitive.title` (+2 same) | حساس به حروف بزرگ و کوچک (لاتین) | بین حروف بزرگ و کوچک انگلیسی فرق گذاشته شود |
| `filter.defs.Condition.ignore_variants.title` (+2 same) | یکسان‌گرفتن حروف عربی و فارسی هم‌شکل (ی و ک) و ارقام فارسی، عربی و لاتین | «ی» و «ک» عربی و فارسی یکی حساب شوند؛ ارقام فارسی، عربی و انگلیسی هم یکی حساب شوند |
| `filter.defs.Condition.op.options.ends_with` | پایان یابد با | با این متن تمام شود |
| `filter.defs.Condition.op.options.starts_with` | شروع شود با | با این متن شروع شود |
| `filter.defs.Condition.op.title` | عملگر | نوع مقایسه |
| `filter.defs.Group.logic.options.and` | همه‌ی شرط‌ها (و) | همه‌ی شرط‌ها درست باشد |
| `filter.defs.Group.logic.options.or` | هرکدام از شرط‌ها (یا) | یکی از شرط‌ها درست باشد |
| `filter.defs.Group.logic.title` | ترکیب | شرط‌ها چطور با هم ترکیب شوند |
| `filter.description` | فقط ردیف‌هایی را نگه می‌دارد که شرط‌ها را برآورده کنند. روی شیت، نتیجه در یک جدول جدید ساخته می‌شود. | فقط ردیف‌هایی را نگه می‌دارد که شرط‌ها را داشته باشند. روی برگه، نتیجه در یک جدول جدید قرار می‌گیرد و برگه‌ی اصلی دست‌نخورده می‌ماند. |
| `find_replace.description` | متن را در ستون‌های متنی جستجو و جایگزین می‌کند. جستجو حرفی است (بدون عبارت منظم). | متن را در ستون‌های متنی پیدا می‌کند و عوض می‌کند. متن را همان‌طور که نوشته‌اید جستجو می‌کند؛ علامت‌هایی مثل * یا ؟ معنای خاصی ندارند. |
| `find_replace.params.match.options.partial` | بخشی از متن سلول | هر جای متنِ خانه |
| `find_replace.params.match.options.whole` | کل متن سلول | فقط وقتی کل متنِ خانه همین باشد |
| `find_replace.params.replace.title` | جایگزین (خالی = حذف) | با این متن عوض شود (خالی = حذف شود) |
| `group_aggregate.defs.Aggregation.fn.options.count` | تعداد (غیرخالی؛ بدون ستون = تعداد ردیف) | تعداد خانه‌های پر (اگر ستونی انتخاب نشود: تعداد ردیف‌ها) |
| `group_aggregate.defs.Aggregation.fn.options.count_distinct` | تعداد مقدارهای متمایز | تعداد مقدارهای غیرتکراری |
| `group_aggregate.defs.Aggregation.fn.title` (+1 same) | تابع | نوع محاسبه |
| `group_aggregate.defs.Aggregation.name.title` | نام ستون خروجی (اختیاری) | نام ستونِ نتیجه (اختیاری) |
| `group_aggregate.defs.Aggregation.title` | محاسبه | یک محاسبه |
| `group_aggregate.description` | ردیف‌ها را بر اساس ستون‌های انتخابی گروه‌بندی می‌کند و جمع، میانگین، تعداد و ... را در یک جدول جدید می‌سازد. داده‌ی اصلی تغییر نمی‌کند. | ردیف‌ها را بر اساس ستون‌هایی که انتخاب می‌کنید گروه می‌کند و برای هر گروه جمع، میانگین، تعداد و مانند آن را حساب می‌کند (مثلاً جمع فروش هر شهر). نتیجه در یک جدول جدید قرار می‌گیرد و داده‌ی اصلی تغییر نمی‌کند. |
| `group_aggregate.params.aggregations.title` | محاسبه‌ها | چه چیزی حساب شود |
| `group_aggregate.params.by.title` | گروه‌بندی بر اساس | گروه‌ها بر اساس کدام ستون‌ها ساخته شوند |
| `join.description` | دو جدول را بر اساس ستون‌های کلید به هم وصل می‌کند. جدول دوم از «هدف‌های اضافی» خوانده می‌شود و نتیجه یک جدول جدید است. | دو جدول را بر اساس یک ستونِ مشترک به هم وصل می‌کند (مثلاً نام هر نفر + شهرش از جدول دیگر). جدول دوم را شما انتخاب می‌کنید و نتیجه در یک جدول جدید قرار می‌گیرد. |
| `join.label` | ترکیب دو جدول (join) | ترکیب دو جدول |
| `join.params.how.options.full` | همه‌ی ردیف‌های هر دو | همه‌ی ردیف‌های هر دو جدول |
| `join.params.how.options.inner` | فقط مشترک‌ها | فقط ردیف‌هایی که در هر دو جدول هستند |
| `join.params.how.title` | نوع اتصال | کدام ردیف‌ها در نتیجه بیایند |
| `join.params.ignore_variants.title` | یکسان‌گرفتن حروف عربی و فارسی هم‌شکل (ی و ک) و ارقام فارسی، عربی و لاتین در کلیدها | «ی» و «ک» عربی و فارسی یکی حساب شوند؛ ارقام فارسی، عربی و انگلیسی هم یکی حساب شوند |
| `join.params.left_on.title` | کلید جدول اول | ستونِ مشترک در جدول اول |
| `join.params.right_on.title` | کلید جدول دوم (به همان ترتیب) | ستونِ مشترک در جدول دوم (به همان ترتیب) |
| `join.params.suffix.title` | پسوند ستون‌های هم‌نام جدول دوم | اگر ستونی در هر دو جدول هم‌نام بود، این متن به نام ستونِ جدول دوم اضافه شود |
| `pivot.description` | مقدارهای یک ستون را به ستون‌های جدید تبدیل می‌کند و در هر خانه یک خلاصه‌ی عددی می‌گذارد. نتیجه یک جدول جدید است. | مقدارهای یک ستون را به ستون‌های جدید تبدیل می‌کند و در هر خانه یک جمع‌بندی عددی می‌گذارد (مثلاً فروش هر شهر در هر فصل). نتیجه در یک جدول جدید قرار می‌گیرد. |
| `pivot.params.fill_value.title` | مقدار خانه‌های خالی (اختیاری) | عدد برای خانه‌های بدون داده (اختیاری) |
| `pivot.params.index.title` | ستون‌های ردیف | ستون‌هایی که ردیف‌ها را مشخص می‌کنند |
| `pivot.params.values.title` | ستون مقدار | ستونی که عددها از آن می‌آید |
| `sort.defs.SortKey.direction.options.asc` | صعودی | صعودی (کوچک به بزرگ، الف تا ی) |
| `sort.defs.SortKey.direction.options.desc` | نزولی | نزولی (بزرگ به کوچک، ی تا الف) |
| `sort.defs.SortKey.direction.title` | جهت | ترتیب |
| `sort.defs.SortKey.nulls.options.first` | اول | بالا |
| `sort.defs.SortKey.nulls.options.last` | آخر | پایین |
| `sort.defs.SortKey.nulls.title` | سلول‌های خالی | خانه‌های خالی کجا بروند |
| `sort.defs.SortKey.title` | کلید | ستون مرتب‌سازی |
| `sort.params.collation.options.binary` | بر اساس کد نویسه | ساده (بر اساس کد حرف‌ها) |
| `sort.params.collation.options.persian` | فارسی (الفبای فارسی) | بر اساس الفبای فارسی |
| `sort.params.collation.title` | روش مقایسه متن | مرتب‌سازی متن |
| `sort.params.keys.description` | ستون‌ها به ترتیب اولویت. | اگر چند ستون بدهید، اول بر اساس ستون اول مرتب می‌شود. |
| `sort.params.keys.title` | کلیدهای مرتب‌سازی | مرتب‌سازی بر اساس |
| `split_column.params.widths.title` | عرض ستون‌ها (تعداد نویسه) | عرض هر بخش (تعداد حرف) |
| `unpivot.description` | جدول عریض را به جدول بلند تبدیل می‌کند (هر ستون مقدار به یک ردیف). نتیجه یک جدول جدید است. | هر ستونِ مقدار را به یک ردیف جدا تبدیل می‌کند (مثلاً ماه‌ها زیر هم قرار می‌گیرند). نتیجه در یک جدول جدید قرار می‌گیرد. |
| `unpivot.params.id_columns.title` | ستون‌های شناسه (ثابت می‌مانند) | ستون‌هایی که کنار هر ردیف تکرار شوند |
| `unpivot.params.value_columns.description` | اگر خالی باشد، همه‌ی ستون‌های غیرشناسه استفاده می‌شوند. | اگر خالی بگذارید، همه‌ی ستون‌های دیگر تبدیل می‌شوند. |
| `unpivot.params.value_columns.title` | ستون‌های مقدار | ستون‌هایی که به ردیف تبدیل شوند |
| `unpivot.params.value_name.title` | نام ستون مقدارها | نام ستونی که مقدارها را نگه می‌دارد |
| `unpivot.params.variable_name.title` | نام ستون عنوان‌ها | نام ستونی که اسم ستون‌های قبلی را نگه می‌دارد |
