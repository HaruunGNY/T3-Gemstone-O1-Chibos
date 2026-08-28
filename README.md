# T3 Gemstone O1 — ChibiOS Üzerinde ArduCopter Kurulumu

Bu doküman, T3 Gemstone O1 kartında gerçek ArduCopter uçuş kontrolcüsünü,
Linux yerine doğrudan kartın **R5F** çekirdeğinde, **ChibiOS** adlı bir
gerçek-zamanlı işletim sistemi (RTOS) üzerinde çalıştırmayı anlatır.

Hedef kitle: bu konuda **hiçbir ön bilgisi olmayan biri**. Terminal kullanmayı
biliyorsanız (komut kopyalayıp yapıştırabiliyorsanız) yeterli — geri kalan her
kavram aşağıda açıklanıyor. Bu kurulum 2026-08-18'de gerçek donanımda uçuşla
doğrulandı, yani burada anlatılanlar "teoride çalışır" değil, fiilen çalışmış
bir sonuç.

## İçindekiler

1. [Bu proje ne, neden var](#1-bu-proje-ne-neden-var)
2. [Kavramlar sözlüğü](#2-kavramlar-sözlüğü-önce-bunu-okuyun)
3. [Güvenlik uyarısı](#3-güvenlik-uyarısı-önce-okuyun)
4. [Gerekli donanım](#4-gerekli-donanım)
5. [Host bilgisayarda yazılım kurulumu](#5-host-bilgisayarda-yazılım-kurulumu)
6. [Depoyu edinme](#6-depoyu-edinme)
7. [Derleme](#7-derleme)
8. [Karta ilk deploy (test amaçlı, kalıcı değil)](#8-karta-ilk-deploy-test-amaçlı-kalıcı-değil)
9. [Kalıcı hale getirme](#9-kalıcı-hale-getirme)
10. [QGroundControl bağlantısı](#10-qgroundcontrol-bağlantısı)
11. [Doğrulama listesi](#11-doğrulama-listesi)
12. [Bilinen kısıtlamalar](#12-bilinen-kısıtlamalar)
13. [Sorun giderme](#13-sorun-giderme)
14. [Depo yapısı](#14-depo-yapısı)

---

## 1) Bu proje ne, neden var

T3 Gemstone O1 kartının içinde **iki farklı işlemci çekirdek ailesi** var,
aynı çip üzerinde ama birbirinden bağımsız çalışıyorlar:

- **A53 çekirdekleri**: normal, güçlü çekirdekler. Üzerlerinde tam bir Linux
  (Ubuntu) çalışır. SSH ile bağlandığınızda girdiğiniz yer burası.
- **MCU domain Cortex-R5F ("R5F")**: çok daha küçük, ayrı bir gömülü çekirdek.
  Kendi başına RAM'i, kendi başına çalışma mantığı var. Linux, `remoteproc`
  adlı bir mekanizmayla bu çekirdeğe bir program (`.elf` dosyası) yükleyip
  başlatabiliyor — tıpkı bir Arduino'ya program yüklemek gibi ama kartın
  kendi içinde, ayrı bir "bilgisayarcık" olarak.

**Kartın fabrika/varsayılan hali:** R5F'te işe yaramaz bir "echo" test
programı boşta duruyor, gerçek uçuş kontrolü A53 tarafında, Linux üzerinde
çalışan ArduCopter yapıyor (`t3-gem-ardupilot` apt paketi).

**Bu kurulumun yaptığı:** ArduCopter'ı Linux'tan R5F'e taşımak. Yani artık
uçuş kontrolü Linux'ta değil, doğrudan o küçük R5F çekirdeğinde, ChibiOS
denen bir RTOS (gerçek-zamanlı işletim sistemi — normal Linux'tan çok daha
basit, öngörülebilir zamanlamalı, gömülü sistemler için tasarlanmış bir
işletim sistemi) üzerinde çalışıyor. Linux'un görevi bu noktadan sonra sadece:

- Açılışta R5F'e doğru programı yüklemek,
- R5F'in ihtiyaç duyduğu donanım yollarını (SPI, PWM) ona bırakmak,
- R5F ile Linux arasında paylaşılan bir bellek bölgesi üzerinden MAVLink
  (yer kontrol istasyonu haberleşme protokolü) trafiğini
  QGroundControl'e (bir "GCS" — Ground Control Station, yer kontrol
  istasyonu yazılımı) köprülemek.

**Bu neden yapılıyor?** R5F, Linux'a göre çok daha az gecikmeli/daha
öngörülebilir zamanlama sunar (gerçek-zamanlı = "her döngü tam olarak ne
zaman çalışacağı garanti edilebilir" demek) — uçuş kontrolü gibi zamanlamaya
duyarlı işler için ilgi çekici bir alternatif. Bu, T3 ekibinden bağımsız bir
geliştiricinin yaptığı, henüz resmi olarak T3'e katılmamış
bir deneysel çalışma.

---

## 2) Kavramlar sözlüğü (önce bunu okuyun)

| Terim | Ne demek |
|---|---|
| **ArduPilot / ArduCopter** | Açık kaynak bir otopilot yazılımı ailesi. ArduCopter, onun multikopter (drone) sürümü. Roll/pitch/yaw stabilizasyonu, GPS pozisyon tutma, arm/disarm güvenlik mantığı gibi her şeyi içerir. |
| **HAL (Hardware Abstraction Layer)** | ArduPilot'un donanımla konuşan katmanı. Aynı ArduCopter kodu, farklı HAL'lar sayesinde farklı donanımlarda (Linux, ChibiOS, vs.) çalışabilir. Bu depodaki özel HAL'ın adı `AP_HAL_ChibiOS_K3`. |
| **RTOS** | Real-Time Operating System — gerçek zamanlı işletim sistemi. Linux gibi "genel amaçlı" değil, "bu görev tam olarak şu kadar sürede bitecek" garantisi verebilen, küçük/gömülü sistemler için işletim sistemi. **ChibiOS** kullanılan RTOS'un adı. |
| **R5F / MCU domain** | Kartın üzerindeki, Linux'un çalıştığı ana çekirdeklerden (A53) tamamen ayrı, küçük bir ARM Cortex-R5F çekirdeği. Bu depo, ArduCopter'ı burada çalıştırıyor. |
| **remoteproc** | Linux çekirdeğinin bir alt sistemi — Linux'un, kendi yanındaki başka bir çekirdeğe (bizim durumumuzda R5F) bir program (.elf) yükleyip başlatmasını/durdurmasını sağlar. `/sys/class/remoteproc/remoteproc2/` altındaki dosyalarla kontrol edilir. |
| **ELF** | Derlenmiş bir programın dosya biçimi (`.elf` uzantılı). Burada "R5F'e yüklenecek program dosyası" anlamında kullanılıyor. |
| **SPI** | Sensörlerle (bu kartta IMU — ivme/gyro sensörü) haberleşmek için kullanılan bir donanım veri yolu (bus). |
| **PWM** | Motorlara/ESC'lere (motor sürücü) hız komutu göndermek için kullanılan sinyal türü. |
| **systemd servisi** | Linux'un açılışta otomatik başlattığı arka plan programı/görevi. `.service` uzantılı dosyalarla tanımlanır. Bu depoda hem kartın kendi Linux'unda hem host bilgisayarda birkaç tane kuruluyor. |
| **MAVLink** | Drone ile yer kontrol istasyonu (QGroundControl gibi) arasındaki standart haberleşme protokolü/mesaj formatı. |
| **QGroundControl (QGC)** | Bilgisayarınızda çalışan, drone'a bağlanıp telemetri gösteren, parametre ayarlayan, arm/disarm yapabildiğiniz yer kontrol istasyonu yazılımı. |
| **waf** | ArduPilot'un kullandığı derleme (build) aracı — `make`'e benzer bir şey, `python3 waf <komut>` şeklinde çalıştırılır. |
| **arm-none-eabi-gcc** | R5F gibi bir ARM gömülü çekirdek için kod üreten bir derleyici (cross-compiler — host bilgisayarınız muhtemelen x86_64 ama R5F ARM, bu yüzden "çapraz derleme" gerekir). |
| **Host (bilgisayar)** | Sizin oturduğunuz, kodu derlediğiniz normal bilgisayarınız. Karttan (T3 Gemstone O1) ayrı bir şey. |
| **Kart / board** | T3 Gemstone O1 — üzerinde hem Linux (A53) hem R5F çalışan fiziksel donanım. |
| **arm / disarm** | Bir drone'un motorlarının dönmeye hazır hale getirilmesi (arm) / güvenli, motorların dönemeyeceği hale getirilmesi (disarm). Uçmadan önce arm edilmesi gerekir. |

---

## 3) GÜVENLİK UYARISI (önce okuyun)

- **Pervaneleri (propeller) çıkarmadan hiçbir arm/motor testi yapmayın.**
  Bu firmware'de arm olduğunda motorlar gerçekten dönebilir.
- Bu kurulumda **GPS çalışmıyor** (bkz. [Bölüm 12](#12-bilinen-kısıtlamalar)) —
  yani Auto/Guided/RTL/PosHold gibi GPS gerektiren modlar **yoktur**. Sadece
  Stabilize/Acro gibi GPS'siz modlar kullanılabilir. RTL (eve dön) gibi bir
  "kurtarma" modu olmadığını bilerek test edin.
- Batarya voltaj/akım telemetrisi yok — bataryanın ne durumda olduğunu
  yazılım size söylemez, gözle/elle takip edin.
- İlk defa deploy ederken/test ederken kart bir tezgahta, pervanesiz,
  sabitlenmiş halde olmalı.

---

## 4) Gerekli donanım

- Bir **T3 Gemstone O1** kartı (üzerinde T3'ün resmi işletim sistemi kurulu
  ve çalışır halde — kartı sıfırdan görüntü yazma/imajlama bu deponun
  konusu değil, resmi rehber için bkz.
  [docs.t3gemstone.org/tr/imager/introduction](https://docs.t3gemstone.org/tr/imager/introduction)).
- Kart ile host bilgisayarı bağlayan bir **USB-C kablo** (kartın
  USB-Ethernet debug bağlantısı için).
- Bir **host bilgisayar** (Linux/Ubuntu önerilir — bu doküman Ubuntu
  varsayıyor).
- (Gerçek uçuş denemesi için) motorlar takılıyken **pervaneler çıkarılmış**
  olmalı, ilk testler için.
- GPS, RC alıcısı, motor/ESC gibi parçaların karta fiziksel olarak hangi
  pinlerden bağlanacağı bu depoda anlatılmıyor (bu depo yazılım/firmware
  tarafını, ChibiOS+R5F kurulumunu anlatıyor) — kablolama için T3'ün resmi
  ArduPilot sayfasına bakın:
  [docs.t3gemstone.org/tr/projects/ardupilot](https://docs.t3gemstone.org/tr/projects/ardupilot).

---

## 5) Host bilgisayarda yazılım kurulumu

Aşağıdakileri host bilgisayarınıza (karta değil!) kurun:

```sh
sudo apt update
sudo apt install -y git make python3 python3-pip sshpass ssh gcc-arm-none-eabi
pip3 install empy==3.3.4
```

Neden bunlar:
- `git` — depoyu indirmek için.
- `make`, `gcc-arm-none-eabi` (`arm-none-eabi-gcc` komutunu sağlar) — R5F
  için kod derlemek için gereken çapraz derleyici.
- `python3`, `python3-pip` — ArduPilot'un `waf` derleme sistemi Python
  tabanlı.
- `empy` — waf'ın derleme sırasında kullandığı bir şablon (template) kütüphanesi.
  `pip install empy==3.3.4` ile kurulmalı; sürüm önemli, farklı bir sürüm
  derleme hatası verebilir.
- `sshpass` — dosya kopyalarken (`scp`) kart parolasını otomatik geçmek
  için (aşağıdaki `scp` komutları bunu kullanıyor). Kart üzerinde komut
  çalıştırmak için ise bir kez `ssh gemstone@192.168.7.2` ile bağlanıp o
  terminali açık bırakacaksınız — parolayı orada elle bir kez girersiniz.

Kurulumun doğru olduğunu kontrol edin:

```sh
arm-none-eabi-gcc --version
python3 -c "import em; print('empy OK')"
```

İkisi de hatasız bir şey yazdırmalı.

---

## 6) Depoyu edinme

Bu depoyu klonlayıp klasörüne girin:

```sh
git clone https://github.com/HaruunGNY/T3-Gemstone-O1-Chibos.git
cd T3-Gemstone-O1-Chibos
```

Depo, aslen ayrı iki proje olan şu ikisini zaten içinde
barındırıyor (siz ayrıca klonlamanıza gerek yok):

- **ArduPilot** (bu deponun kökü) — [emirhan-sonmez/ardupilot](https://github.com/emirhan-sonmez/ardupilot),
  dal `gemstone-o1-r5f-hal`. Gerçek ArduCopter kodu + R5F'e özel HAL:
  [libraries/AP_HAL_ChibiOS_K3/](libraries/AP_HAL_ChibiOS_K3/).
- **ChibiOS portu** — [emirhan-sonmez/ChibiOS-Gemstone-O1-Port](https://github.com/emirhan-sonmez/ChibiOS-Gemstone-O1-Port),
  dal `gemstone-o1-r5f`, [modules/ChibiOS-Gemstone-O1-Port/](modules/ChibiOS-Gemstone-O1-Port/)
  altında — yukarıdakinin derleme zamanı bağımlılığı.

`deploy/` klasörü altında ayrıca, yukarıdaki iki kaynak depoda de
bulunmayan, bu proje için özel yazılmış parçalar var: kart üzerinde
çalışan bir parametre kaydetme programı, host↔kart arası MAVLink köprüsü,
ve gerekli systemd servis tanımları. Bunlara ilerleyen bölümlerde
değinilecek.

---

## 7) Derleme

Depo klasörünün içindeyken:

```sh
python3 waf configure --board GemstoneO1R5F
python3 waf copter
```

Ne oluyor: ilk komut derleme ayarlarını R5F/ChibiOS hedefine göre
yapılandırıyor (ChibiOS portunun konumunu otomatik buluyor, siz bir şey
ayarlamanıza gerek yok). İkinci komut asıl derlemeyi yapıp ArduCopter'ı
üretiyor.

**İlk çalıştırmada internet gerekir** — waf kendi alt bileşenini
(`modules/waf`) otomatik indirmeye çalışır. "Tekrar çalıştırın" gibi bir
mesaj görürseniz komutu tekrar çalıştırmanız yeterli.

Başarılı bir derleme sonunda şu dosya oluşur:

```
build/GemstoneO1R5F/bin/arducopter
```

Bu, R5F'e yükleyeceğiniz asıl program dosyasıdır (bir ELF dosyası).

---

## 8) Karta ilk deploy (test amaçlı, kalıcı değil)

Kart bilgileri (hepsi T3'ün resmi imajının varsayılanı):

- Adres: `192.168.7.2` (USB-Ethernet debug kablosu üzerinden)
- Kullanıcı: `gemstone`
- SSH parolası: `gem`
- sudo parolası: `gem`

Kartı USB-C kablo ile host bilgisayara bağlayın, kartın açık olduğundan
emin olun. Bundan sonra iki terminal kullanacaksınız.

**Host terminali** — derlenen dosyayı karta kopyalayın:

```sh
sshpass -p gem scp build/GemstoneO1R5F/bin/arducopter gemstone@192.168.7.2:/tmp/ap-k3.elf
```

**Kart terminali** — karta bir kez bağlanın ve bu oturumu açık bırakın:

```sh
ssh gemstone@192.168.7.2   # parola: gem
```

Bundan sonraki tüm kart-tarafı komutları (bu bölümde ve devamındaki
bölümlerde) artık o açık kalan terminalde çalıştıracaksınız — her komut
için ayrıca `ssh`/`sshpass` yazmanıza gerek yok, `sudo` parola sorduğunda
elle `gem` yazın:

```sh
sudo systemctl stop arducopter
sudo sh -c 'echo 4b00000.spi > /sys/bus/platform/drivers/omap2_mcspi/unbind'
sudo cp /tmp/ap-k3.elf /lib/firmware/ap-k3.elf
sudo sh -c 'echo stop > /sys/class/remoteproc/remoteproc2/state'
sudo sh -c 'echo ap-k3.elf > /sys/class/remoteproc/remoteproc2/firmware'
sudo sh -c 'echo start > /sys/class/remoteproc/remoteproc2/state'
```

Satır satır ne yapıyor:
1. Linux/A53 tarafındaki eski ArduCopter servisini durdurur (artık R5F
   devralacak).
2. IMU sensörünün bağlı olduğu SPI yolunu Linux'un elinden alıp R5F'e
   serbest bırakır (ikisi aynı anda kullanamaz).
3. Dosyayı, remoteproc'un beklediği konuma (`/lib/firmware/`) kopyalar.
4-6. remoteproc'a "durdur, şu yeni dosyayı yükle, başlat" der.

**ÖNEMLİ KISITLAMA — mutlaka okuyun:** yukarıdaki bloktaki `remoteproc2/state`'e
`"stop"` yazan komut **sadece R5F o an TI'nın fabrika/stok firmware'ini
çalıştırıyorsa** düzgün çalışır.
Bizim kendi (ChibiOS/ArduCopter) firmware'imiz, remoteproc'un "durdur"
komutu için beklediği özel bir el sıkışma sinyalini (mailbox) henüz
implement etmiyor. Yani **R5F zaten bizim firmware'imizi çalıştırıyorsa,
yukarıdaki sıralamayla yeni bir sürüm YÜKLEYEMEZSİNİZ** — önce kartı
**tamamen reboot etmeniz** gerekir:

```sh
sudo reboot
```

Bu komutu çalıştırdığınız an kart terminaliniz kopar (kart yeniden
başlıyor). Birkaç saniye bekleyip `ssh gemstone@192.168.7.2` ile tekrar
bağlanın (`ping 192.168.7.2` ile de kartın geri geldiğini kontrol
edebilirsiniz), sonra yukarıdaki 6 kart-terminali komutunu tekrar
çalıştırın (dosya zaten `/tmp/ap-k3.elf`'te duruyorsa scp adımını
tekrarlamanıza gerek yok). **Yani her kod değişikliğinde döngü şu: reboot
→ yeniden bağlan → yukarıdaki 6 komut.**

Programın kart üzerinde ne yazdırdığını görmek için (kart terminalinde):

```sh
sudo cat /sys/kernel/debug/remoteproc/remoteproc2/trace0
```

Bu, programın kendi tanılama/debug çıktısıdır (`trace0`). **16 KB ile
sınırlı ve dairesel değildir** — dolunca yeni yazma durur, yani çok uzun
süre çalışan bir programın çok eski çıktılarını burada göremezsiniz.

---

## 9) Kalıcı hale getirme

Yukarıdaki bölüm, her reboot'ta kaybolan **geçici** bir test. Kartın **her
açılışında otomatik olarak** bu firmware ile gelmesi için:

Host terminalinde, dosyayı karta kopyalayın:

```sh
sshpass -p gem scp build/GemstoneO1R5F/bin/arducopter gemstone@192.168.7.2:/tmp/ap-k3.elf
```

Kart terminalinde (açık SSH oturumunuzda):

```sh
# a) Orijinal fabrika firmware'ini yedekleyin (daha önce yedeklenmediyse)
sudo sh -c 'test -f /lib/firmware/j722s-mcu-r5f0_0-fw.bak || cp /lib/firmware/j722s-mcu-r5f0_0-fw /lib/firmware/j722s-mcu-r5f0_0-fw.bak'

# b) Kopyaladığınız dosyayı, remoteproc'un OTOMATİK yüklediği varsayılan dosyanın üzerine yazın
sudo cp /tmp/ap-k3.elf /lib/firmware/j722s-mcu-r5f0_0-fw

# c) Linux tarafındaki eski ArduCopter servisini KALICI olarak kapatın
sudo systemctl disable --now arducopter
```

Sonra [Bölüm 9.1](#91-3-adet-kart-üzerinde-çalışan-systemd-servisi)'deki 3
servisi kurun, ardından reboot atıp doğrulayın (kart terminalinde):

```sh
sudo reboot
```

**Geri alma** (her şeyi eski haline, Linux/ArduCopter'a döndürmek için —
kart terminalinde):

```sh
sudo cp /lib/firmware/j722s-mcu-r5f0_0-fw.bak /lib/firmware/j722s-mcu-r5f0_0-fw
sudo systemctl disable chibios-spi-release chibios-pwm-clocks gem-storaged
sudo systemctl enable arducopter
sudo reboot
```

### 9.1) 3 adet kart üzerinde çalışan systemd servisi

Bunların üçü de **kartın kendi Linux'unda** çalışır (host bilgisayarda
değil). Aşağıda bunları SSH ile kuracağız, ama bu sadece dosyayı karta
kopyalayıp systemd'ye "bunu her açılışta çalıştır" demekten ibaret —
kurulum bittikten sonra bu servisler tamamen kartın kendi systemd'i
tarafından yönetilir, host bilgisayara veya SSH'a bir daha ihtiyaç
duymadan.

Bunlar özellikle açılışın **çok erken bir aşamasında** çalışacak şekilde
ayarlanmış: `sysinit.target`. Bir Linux açılırken servisler sırayla ayağa
kalkar: önce disk/dosya sistemleri hazırlanır (`sysinit.target`), sonra
temel sistem servisleri (`basic.target`), en son da ağ ve SSH gibi
"günlük kullanım için" servisler. Bu 3 servis en baştaki `sysinit.target`
aşamasına bağlı — yani kartın ağı (dolayısıyla SSH bağlantısı) daha
ayağa kalkmadan bunlar çoktan çalışmış oluyor. Bunun neden önemli olduğu
aşağıda `gem-storaged` örneğiyle anlatılıyor. Tanımları
[deploy/systemd-board/](deploy/systemd-board/) altında:

| Servis | Ne işe yarar | Neden gerekli |
|---|---|---|
| `chibios-spi-release.service` | SPI0 yolunu Linux'tan alıp R5F'e serbest bırakır | IMU sensörü SPI0 üzerinde; ikisi aynı anda erişirse çakışır |
| `chibios-pwm-clocks.service` | Motor PWM saat sinyallerini açar | **Çok kritik.** Bu olmadan arm işlemi başarılı görünür ama motorlar dönmez — bu saatleri normalde Linux'taki eski ArduCopter servisi kendiliğinden açardı, o kapatıldığı için artık hiçbir şey açmıyor |
| `gem-storaged.service` | Parametre/kalibrasyon verisini kalıcı diske yazar | R5F'in yazdığı ayarlar (RC kalibrasyonu, PID'ler, vb.) normalde uçtuğu paylaşımlı bellek reboot'ta silinir; bu servis onları gerçek diske kaydeder |

**`gem-storaged` neden mutlaka kartın kendisinde otomatik başlamalı, SSH
ile elle/uzaktan tetiklenerek değil — somut bir örnekle:**

`gem-storaged`'ın işi, R5F'in bellekte tuttuğu kalibrasyon/ayar verisini
(RC kalibrasyonu, PID değerleri vb.) gerçek diske kaydetmek. Bu servis
çalışmazsa bu veriler her reboot'ta sıfırlanıyor.

Bir ara bu servis, host bilgisayardan SSH ile "kart açıldı, şimdi şu
script'i çalıştır" şeklinde **her reboot'ta yeniden tetiklenen** bir
yöntemle kurulmuştu. Bu neden riskliydi:

1. Kart yeniden başladığında, host'un SSH ile bağlanabilmesi için önce
   Linux tamamen açılmalı, sonra kartın USB-Ethernet ağı (`usb0`) ayağa
   kalkmalı. Bu süre sabit değil — bazen birkaç saniye, bazen daha uzun
   sürebiliyor.
2. R5F tarafındaki ArduCopter ise açılışta kalibrasyon verisini en fazla
   **60 saniye** bekliyor; bu süre içinde veri gelmezse "demek ki yok"
   deyip boş/varsayılan bir veriyle devam ediyor.
3. Bir seferinde ağın hazır olması 60 saniyeden uzun sürdü. SSH bağlantısı
   kurulup `gem-storaged` fiilen çalışmaya başlayana kadar ArduCopter
   zaten pes etmiş ve **gerçek kalibrasyon verisinin üzerine boş bir veri
   yazmıştı** — bu veri bir daha geri gelmedi.

Kesin çözüm: servisin başlamasını hiçbir şekilde ağa/SSH'a/host
bilgisayara bağlı olmayan bir mekanizmaya bağlamak. Yukarıda anlatılan
`sysinit.target`, kartın kendi Linux çekirdeği tarafından — USB kablosu
takılı olsun olmasın, host bilgisayar açık olsun olmasın — otomatik
tetiklenen bir aşama. Bu sayede `gem-storaged` artık her zaman
ArduCopter'ın 60 saniyelik penceresinden çok önce hazır oluyor ve yarış
durumu (iki şeyin kimin önce yetişeceğine bağlı olarak sonucun
değişmesi) tamamen ortadan kalkıyor.

**Olası kafa karışıklığı:** Az aşağıdaki kurulum komutları da SSH
kullanıyor — bu tamamen normal, yukarıdaki sorunla çelişmiyor. Aradaki
fark şu: aşağıdaki SSH komutları sadece dosyayı karta kopyalayıp
systemd'ye "bunu kaydet, açılışta çalıştır" demek için **bir kereye
mahsus** çalıştırılıyor — bir kurulum aracı olarak SSH. Kurulum bitince
SSH'ın bu servisle bir ilgisi kalmıyor; servis artık kartın kendi
systemd'i tarafından, her açılışta otomatik olarak, SSH'a hiç ihtiyaç
duymadan başlatılıyor. Sorun yaratan eski yöntemde ise SSH bir kurulum
aracı değil, servisin **her seferinde fiilen çalışabilmesinin ön koşulu**
haline gelmişti — asıl fark budur.

Her birini kurmak için (`<dosya>` yerine servis adını yazın):

Host terminalinde, dosyayı karta kopyalayın:

```sh
sshpass -p gem scp deploy/systemd-board/<dosya>.service gemstone@192.168.7.2:/tmp/<dosya>.service
```

Kart terminalinde:

```sh
sudo cp /tmp/<dosya>.service /etc/systemd/system/<dosya>.service
sudo systemctl daemon-reload
sudo systemctl enable --now <dosya>.service
```

`gem_storaged.service`'in çalıştırdığı Python betiğini de ayrıca kopyalamanız
gerekiyor — host terminalinde:

```sh
sshpass -p gem scp deploy/board/gem_storaged.py gemstone@192.168.7.2:/tmp/gem_storaged.py
```

kart terminalinde:

```sh
sudo cp /tmp/gem_storaged.py /home/gemstone/gem_storaged.py
```

---

## 10) QGroundControl bağlantısı

R5F üzerindeki ArduCopter, MAVLink verisini fiziksel bir kabloya değil,
Linux ile paylaştığı bir bellek bölgesine (adres `0xA1120000`, 64 KiB)
yazıp okuyor — buna "ring buffer" (dairesel tampon) deniyor. Bu veriyi
QGroundControl'ün anlayacağı normal bir ağ bağlantısına (UDP 14550)
çevirmek için host bilgisayarınızda iki Python betiği çalışır
([deploy/host/](deploy/host/)):

- `gem_mavbridge.py` — kartın üzerinde çalışır (host'tan SSH ile
  başlatılır), o paylaşımlı belleği okuyup/yazıp host'a aktarır.
- `run_bridge.py` — host bilgisayarınızda çalışır, SSH üzerinden yukarıdaki
  betiği başlatır, gelen veriyi QGroundControl'ün dinlediği UDP 14550
  portuna yönlendirir. Bağlantı koparsa (örn. kart reboot olduysa)
  otomatik olarak yeniden dener.

Host bilgisayarınızda arka planda sürekli çalışması için bir kullanıcı
systemd servisi olarak kurulur:

```sh
mkdir -p ~/.config/systemd/user
cp deploy/systemd-host/gem-mavbridge.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now gem-mavbridge
loginctl enable-linger "$USER"
```

(`deploy/systemd-host/gem-mavbridge.service` içindeki `ExecStart` satırının
`run_bridge.py` dosyanızın gerçek konumuna işaret ettiğinden emin olun.)

`loginctl enable-linger` komutu, siz oturumu kapatsanız bile bu servisin
arka planda çalışmaya devam etmesini sağlar.

Kurulum bittikten sonra QGroundControl'ü açmanız yeterli — herhangi bir
özel ayar yapmadan otomatik olarak UDP 14550'yi dinler ve bağlanır.
"Not Ready" yazısı ve ArduPilot logosu görürseniz bağlantı başarılıdır.

---

## 11) Doğrulama listesi

Her şeyin doğru kurulduğunu teyit etmek için:

Kart terminalinde:

```sh
# R5F kendi firmware'ini otomatik yüklüyor mu:
cat /sys/class/remoteproc/remoteproc2/state /sys/class/remoteproc/remoteproc2/firmware
# -> "running" ve "j722s-mcu-r5f0_0-fw" yazmalı

# Linux tarafındaki eski ArduCopter gerçekten kapalı mı:
systemctl is-active arducopter; systemctl is-enabled arducopter
# -> inactive / disabled yazmalı

# 3 kart-üzeri servis çalışıyor mu:
systemctl is-active chibios-spi-release chibios-pwm-clocks gem-storaged
# -> üçü de "active" yazmalı
```

Host terminalinde:

```sh
# Host'taki köprü servisi çalışıyor mu:
systemctl --user is-active gem-mavbridge
# -> "active" yazmalı
```

Sonra QGroundControl'ü açın — "Not Ready" / "Stabilize" + ArduPilot logosu
görünmeli.

---

## 12) Bilinen kısıtlamalar

Bunlar 2026-08-18'deki doğrulanmış uçuş anındaki gerçek durumdur — birer
"bug" değil, bu deneysel kurulumun şu anki gerçek sınırları:

- **Chibos için GPS henüz
  test edilmedi.** Normal Linux/ArduCopter kurulumunda GPS `UART-MAIN6`
  adlı seri porta bağlı ve orada sorunsuz çalışıyor (bu portun kartın
  üzerinde tam olarak hangi pin olduğu T3'ün
  [ArduPilot sayfasında](https://docs.t3gemstone.org/tr/projects/ardupilot)
  anlatılıyor). Ama bu depodaki ChibiOS/R5F HAL'inde (`AP_HAL_ChibiOS_K3`)
  o portun karşılığı olan `serial3` hâlâ boş bir stub — gerçek bir
  sürücüsü yazılmadı. Eskiden "R5F bu porta fiziksel olarak hiç
  erişemez" deniyordu; bu iddia sonradan şüpheli çıktı (R5F zaten aynı
  donanım ailesinden başka bir porta — RC girişi için — başarıyla
  erişiyor), bunun üzerine sadece erişilebilirliği sınayan minimal bir
  test kodu (`am67_uart6_probe`) yazılıp derlendi ama **gerçek kartta
  hiç çalıştırılmadı** (bkz. [Bölüm 13](#13-sorun-giderme)'teki not).
  Yani altyapı hazır, doğrulama yapılmadı. Bugün itibariyle sonuç aynı:
  GPS gerektiren modlar (Auto, Guided, RTL, PosHold) **kullanılamaz** —
  sadece Stabilize/Acro gibi GPS'siz modlar çalışır.
- **IMU okuma hızı 100Hz'e sabit.** Daha hızlı bir okuma yöntemi
  denenmişti ama sessizce hatalı veri üretiyordu (her eksende 1 bit
  bozuluyordu), bu yüzden bilinçli olarak yavaş ama güvenilir yönteme
  geri dönüldü. Sonuç: ArduCopter'ın standart 400Hz döngü hızı
  desteklenmiyor, `SCHED_LOOP_RATE` parametresini QGroundControl'den
  (ya da MAVLink üzerinden) **`50`** yapmanız gerekiyor, yoksa "Main loop
  slow" / "Gyro rate" hatası alıp arm edemezsiniz.
- **`ARMING_CHECK` parametresi "eksik" görünüyor**, QGC bir uyarı
  gösteriyor — zararsız bir kozmetik sorun (ArduPilot'un kendisi bu
  parametrenin adını yakın zamanda değiştirdi, QGC'nin dahili listesi
  henüz güncellenmedi). Arm'ı veya uçuşu engellemiyor, görmezden
  gelebilirsiniz.
- **Her firmware değişikliğinde tam reboot şart** (bkz. Bölüm 8) — ileride
  düzeltilebilir bir eksiklik, henüz düzeltilmedi.
- **`trace0` debug çıktısı sınırlı** — 16 KB, dairesel değil. Uzun süre
  çalışan bir programın eski çıktılarını göremezsiniz, sadece anlık
  tanılama için kullanışlı.
- **Batarya voltaj/akım telemetrisi yok** — donanımsal olarak bu kartta
  böyle bir ölçüm devresi tanımlı değil.

---

## 13) Sorun giderme

**"can't stop rproc: -16" veya "module-reset assert failed, ret=-19" hatası
alıyorum:** R5F şu an kendi (ChibiOS) firmware'imizi çalıştırıyor ve bu
firmware "durdur" komutuna düzgün cevap vermiyor. Çözüm: kartı tam reboot
edin, SSH geri geldikten sonra deploy adımlarını (Bölüm 8) baştan
uygulayın. Kısayol yok, her seferinde reboot gerekiyor.

**Arm oluyor ama motorlar hiç dönmüyor:** `chibios-pwm-clocks.service`
kurulu ve çalışır durumda mı kontrol edin (Bölüm 9.1). Bu servis
olmadan motor sürücü saatleri hiç açılmıyor.

**QGroundControl bağlanmıyor:** Sırasıyla kontrol edin: (1) kart açık ve
USB-C ile bağlı mı, (2) `systemctl --user is-active gem-mavbridge` "active"
diyor mu, (3) R5F gerçekten çalışıyor mu (`remoteproc2/state` → "running").

**Kalibrasyon/ayarlar reboot sonrası kayboluyor:** `gem-storaged.service`
kurulu mu ve **board-native** mi (SSH ile değil, kartın kendi systemd'i
üzerinden) çalıştığını doğrulayın — SSH ile tetiklenen bir sürüm bir kez
gerçek veriyi silmişti (Bölüm 9.1'deki uyarıya bakın).

**`/dev/mem` üzerinden bir şey okurken/yazarken "Bus error" ile program
çöküyor:** Bu kartta, R5F ile paylaşılan bellek bölgelerine erişirken hem
başlangıç hem bitiş adresinin 8 byte'a hizalı olması zorunlu — değilse
gerçek bir donanım hatasıyla (SIGBUS) çöker. `deploy/`'daki Python
betiklerindeki `read_aligned()`/`write_aligned()` fonksiyonları bunu zaten
hallediyor; kendi ek bir betik yazarsanız aynı kurala uyun.

**GPS'i çalıştırmayı denemek istiyorum:** Şu an araştırma aşamasında —
GPS'in bağlı olduğu seri portun (`UART-MAIN6`) aynı IP ailesinden, R5F'in
zaten başarıyla eriştiği başka bir port ile aynı donanım bölgesinde olduğu
tespit edildi, yani "R5F oraya hiç erişemez" varsayımı kesin değil. Henüz
gerçek donanımda doğrulanmadı. Bu konuda ilerlemek isterseniz projenin
güncel durumunu takip eden kişiyle konuşun.

---

## 14) Depo yapısı

```
.                                  ArduPilot kaynağı (emirhan-sonmez/ardupilot @ gemstone-o1-r5f-hal)
├── libraries/AP_HAL_ChibiOS_K3/   R5F için özel HAL backend
├── modules/ChibiOS-Gemstone-O1-Port/   ChibiOS portu (emirhan-sonmez/ChibiOS-Gemstone-O1-Port @ gemstone-o1-r5f)
└── deploy/                        Karta/host'a kurulan, hiçbir kaynak repoda olmayan parçalar
    ├── board/gem_storaged.py      Kart üzerinde çalışan parametre kaydetme betiği
    ├── host/gem_mavbridge.py, run_bridge.py   Host↔kart MAVLink köprüsü
    ├── systemd-board/             3 kart-üzeri (board-native) servis tanımı
    └── systemd-host/              Host'taki systemd --user servis tanımı
```

Orijinal ArduPilot projesi hakkında genel bilgi için:
[README_ARDUPILOT.md](README_ARDUPILOT.md).
