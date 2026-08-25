# T3 Gemstone O1 — ArduCopter on ChibiOS (MCU R5F)

Gerçek ArduCopter'ı, T3 Gemstone O1 kartının Linux/A53 çekirdekleri yerine
doğrudan **MCU domain Cortex-R5F** çekirdeğinde, ChibiOS RTOS üzerinde
çalıştıran kurulum. Bu depo, 2026-08-18'de gerçek uçuşla doğrulanmış hâliyle
gereken **tüm parçaları tek bir yerde** toplar: ArduPilot kaynağı + özel HAL,
altında çalışan ChibiOS portu, ve karta/host'a kurulan tüm dağıtım (deploy)
dosyaları.

## Bu ne, neden var

T3 Gemstone O1 kartının iki ayrı işlemci çekirdeği var:

- **A53 çekirdekleri**: normal Linux çalışır (Ubuntu), SSH ile buradan girilir.
- **MCU domain Cortex-R5F ("R5F")**: ayrı, küçük bir gömülü çekirdek. Linux'un
  `remoteproc` mekanizmasıyla bu çekirdeğe bir `.elf` firmware yüklenip
  çalıştırılabilir.

Kartın varsayılan hâli: R5F'te TI'ın stok "echo" firmware'i (işe yaramaz),
Linux tarafında ArduCopter gerçek uçuş kontrolcüsü olarak çalışır
(`AP_HAL_Linux`, apt paketi `t3-gem-ardupilot`).

**Bu kurulum farklı**: ArduCopter'ı Linux'ta değil, doğrudan R5F'te, ChibiOS
RTOS'unun üzerinde çalıştırıyor (özel bir AP_HAL backend: `AP_HAL_ChibiOS_K3`).
Linux tarafındaki ArduCopter servisi kalıcı olarak kapatılır. Linux'un görevi
artık sadece: R5F'i her açılışta bu firmware ile başlatmak, R5F'in ihtiyaç
duyduğu donanım kaynaklarını (SPI0, PWM saatleri) açmak, ve R5F ile paylaşılan
bellek üzerinden MAVLink/parametre trafiğini QGroundControl'e köprülemek.

Bu kurulumun QGroundControl'e tam, gerçek MAVLink (parametreler, kalibrasyon,
arm/disarm, hepsi) ile bağlanabildiği ve gerçekten **uçtuğu** doğrulandı.

## Bu depo neyi birleştiriyor

Aslen ayrı iki depo olan şu ikisi, orijinal (2026-08-18, uçan) kaynak
hâliyle burada tek repo olarak birleştirildi:

- **ArduPilot fork** — [emirhan-sonmez/ardupilot](https://github.com/emirhan-sonmez/ardupilot),
  dal `gemstone-o1-r5f-hal`. Bu deponun kökü. Gerçek ArduCopter uygulaması +
  R5F için yazılmış özel HAL backend: [libraries/AP_HAL_ChibiOS_K3/](libraries/AP_HAL_ChibiOS_K3/).
- **ChibiOS portu** — [emirhan-sonmez/ChibiOS-Gemstone-O1-Port](https://github.com/emirhan-sonmez/ChibiOS-Gemstone-O1-Port),
  dal `gemstone-o1-r5f`. Yukarıdakinin derleme bağımlılığı; burada
  [modules/ChibiOS-Gemstone-O1-Port/](modules/ChibiOS-Gemstone-O1-Port/) altında.

İki depo, tüm katkı/orijinal geliştirme **emirhan-sonmez**'e ait. Bu repo
onları tek klasörde derlenebilir hâlde toplayan, T3 Gemstone O1 kartında
gerçekten uçuşla doğrulanmış bir anlık görüntü (snapshot).

`deploy/` altında ayrıca karta ve host makineye kurulan, kaynak
depolarının hiçbirinde bulunmayan parçalar var: board-native parametre
depolama daemon'u, host↔R5F arası paylaşımlı bellek üzerinden MAVLink
köprüsü, ve 4 systemd servis dosyası.

## Gereksinimler (host / geliştirme makinesi)

- `arm-none-eabi-gcc` (10-2020-q4-major ile derlendi/test edildi)
- `python3`, `python3-pip`
- `empy` (`pip install empy==3.3.4`, ya da `python3 -c "import em"` ile zaten
  var mı kontrol edin — paket `em` olarak import edilir)
- `git`, `make`

## Derleme

```
python3 waf configure --board GemstoneO1R5F
python3 waf copter
```

`GEMSTONE_CHIBIOS_ROOT` env var'ı ayarlamaya gerek yok — varsayılan olarak
depo içindeki `modules/ChibiOS-Gemstone-O1-Port/` kullanılır (bkz.
[Tools/ardupilotwaf/chibios_k3.py](Tools/ardupilotwaf/chibios_k3.py)).
Farklı bir ChibiOS portu denemek isterseniz env var ile override edebilirsiniz.

Çıktı: `build/GemstoneO1R5F/bin/arducopter` (ELF, remoteproc uyumlu —
`.resource_table@0xA1100000`, `.trace@0xA1110000` 16K, `.ipc@0xA1120000` 64K
bölümleri içerir).

İlk `waf configure` waf'ın kendi `modules/waf` submodule'ünü otomatik çekmeye
çalışır, internet gerekir; "tekrar çalıştırın" derse tekrar çalıştırın.

## Karta ilk deploy ve kalıcı hâle getirme

Kart bilgileri: `gemstone@192.168.7.2` (USB-Ethernet debug linki), şifre
`gem`, sudo şifresi de `gem` (T3'ün resmi imajının varsayılanı).

### 1) Tek seferlik deploy ile test (henüz kalıcı değil)

```sh
sshpass -p gem scp build/GemstoneO1R5F/bin/arducopter gemstone@192.168.7.2:/tmp/ap-k3.elf
sshpass -p gem ssh gemstone@192.168.7.2 "echo gem | sudo -S systemctl stop arducopter"
sshpass -p gem ssh gemstone@192.168.7.2 "echo gem | sudo -S sh -c 'echo 4b00000.spi > /sys/bus/platform/drivers/omap2_mcspi/unbind'"
sshpass -p gem ssh gemstone@192.168.7.2 "echo gem | sudo -S cp /tmp/ap-k3.elf /lib/firmware/ap-k3.elf"
sshpass -p gem ssh gemstone@192.168.7.2 "echo gem | sudo -S sh -c 'echo stop > /sys/class/remoteproc/remoteproc2/state'"
sshpass -p gem ssh gemstone@192.168.7.2 "echo gem | sudo -S sh -c 'echo ap-k3.elf > /sys/class/remoteproc/remoteproc2/firmware'"
sshpass -p gem ssh gemstone@192.168.7.2 "echo gem | sudo -S sh -c 'echo start > /sys/class/remoteproc/remoteproc2/state'"
```

**Önemli kısıtlama**: `"stop"` komutu sadece R5F o an TI'ın stok firmware'ini
çalıştırıyorsa düzgün çalışır. Kendi (ChibiOS) firmware'imiz remoteproc'un
`"stop"` için beklediği mailbox el sıkışmasını implement etmiyor — bu yüzden
**her firmware değişikliğinden önce tam reboot atmak şart** (yukarıdaki
sırayla değil; önce `sudo reboot`, SSH geri gelince yukarıdaki adımlar).

Trace'i izlemek için:

```sh
sshpass -p gem ssh gemstone@192.168.7.2 "echo gem | sudo -S cat /sys/kernel/debug/remoteproc/remoteproc2/trace0"
```

### 2) Kalıcı hâle getirme (her reboot'ta otomatik bu firmware gelsin)

```sh
# a) Orijinal stok firmware'i yedekleyin (yoksa)
sshpass -p gem ssh gemstone@192.168.7.2 "echo gem | sudo -S sh -c 'test -f /lib/firmware/j722s-mcu-r5f0_0-fw.bak || cp /lib/firmware/j722s-mcu-r5f0_0-fw /lib/firmware/j722s-mcu-r5f0_0-fw.bak'"

# b) Kendi elf'inizi varsayılan firmware dosyasının üzerine yazın
sshpass -p gem scp build/GemstoneO1R5F/bin/arducopter gemstone@192.168.7.2:/tmp/ap-k3.elf
sshpass -p gem ssh gemstone@192.168.7.2 "echo gem | sudo -S cp /tmp/ap-k3.elf /lib/firmware/j722s-mcu-r5f0_0-fw"

# c) ArduCopter/Linux servisini kalıcı olarak kapatın
sshpass -p gem ssh gemstone@192.168.7.2 "echo gem | sudo -S systemctl disable --now arducopter"

# d) deploy/systemd-board/ altındaki 3 servisi kurun (aşağıya bakın)

# e) reboot atıp doğrulayın
sshpass -p gem ssh gemstone@192.168.7.2 "echo gem | sudo -S reboot"
```

**Geri alma** (ArduCopter/Linux'u tekrar varsayılan yapmak için):

```sh
sshpass -p gem ssh gemstone@192.168.7.2 "echo gem | sudo -S cp /lib/firmware/j722s-mcu-r5f0_0-fw.bak /lib/firmware/j722s-mcu-r5f0_0-fw"
sshpass -p gem ssh gemstone@192.168.7.2 "echo gem | sudo -S systemctl disable chibios-spi-release chibios-pwm-clocks gem-storaged"
sshpass -p gem ssh gemstone@192.168.7.2 "echo gem | sudo -S systemctl enable arducopter"
sshpass -p gem ssh gemstone@192.168.7.2 "echo gem | sudo -S reboot"
```

## Kartta gerekli 3 systemd servisi

Üçü de kartın kendi Linux'unda çalışır (host'ta değil), boot'un çok erken
aşamasında (`sysinit.target`), R5F'in ihtiyaçlarını R5F daha kendi init'ini
bitirmeden hazır hâle getirmek için. Tanımları [deploy/systemd-board/](deploy/systemd-board/) altında:

- **`chibios-spi-release.service`** — SPI0'ı (`4b00000.spi`) Linux'tan R5F'e
  serbest bırakır. IMU (ICM-20948) SPI0 üzerinde; Linux'un `omap2_mcspi`
  sürücüsü aynı anda bağlıysa transferler çakışır.
- **`chibios-pwm-clocks.service`** — EHRPWM0/EHRPWM1 saatlerini açar. **Çok
  önemli**, unutulursa "arm oldu ama motorlar dönmüyor" olur — bu saatleri
  normalde Linux'taki `arducopter.service` kendi PWM çıktısı için açardı (yan
  etki olarak); onu kapattığımız için başka hiçbir şey bu saatleri açmıyor.
- **`gem-storaged.service`** — [deploy/board/gem_storaged.py](deploy/board/gem_storaged.py)'yi
  çalıştırır: `AP_HAL_ChibiOS_K3`'ün parametreleri yazdığı paylaşımlı
  bellekteki 16 KiB'lik alanı gerçek diske kalıcı yazar. **Board-native olmak
  zorunda** (SSH ile değil) — SSH ile tetiklenen bir sürüm, reboot sonrası
  ağın hazır olmasıyla ArduCopter'ın 60 saniyelik bekleme penceresi arasında
  yarış durumuna girip bir kalibrasyonu kalıcı olarak silmişti; board-native
  olması bu riski tamamen ortadan kaldırır. `gem_storaged.py`'nin kendisi
  karta ayrıca kopyalanmalı: `/home/gemstone/gem_storaged.py`.

Kurmak için (her biri için):

```sh
sshpass -p gem scp deploy/systemd-board/<dosya>.service gemstone@192.168.7.2:/tmp/<dosya>.service
sshpass -p gem ssh gemstone@192.168.7.2 "echo gem | sudo -S cp /tmp/<dosya>.service /etc/systemd/system/<dosya>.service"
sshpass -p gem ssh gemstone@192.168.7.2 "echo gem | sudo -S systemctl daemon-reload"
sshpass -p gem ssh gemstone@192.168.7.2 "echo gem | sudo -S systemctl enable --now <dosya>.service"
```

`gem_storaged.py`'yi ayrıca kopyalayın:

```sh
sshpass -p gem scp deploy/board/gem_storaged.py gemstone@192.168.7.2:/tmp/gem_storaged.py
sshpass -p gem ssh gemstone@192.168.7.2 "echo gem | sudo -S cp /tmp/gem_storaged.py /home/gemstone/gem_storaged.py"
```

## MAVLink → QGroundControl köprüsü (host tarafı)

R5F'teki ArduCopter, gerçek MAVLink'i fiziksel bir pime değil, paylaşımlı
bellekteki iki yönlü bir "ring buffer"a yazar/okur (wire contract:
[libraries/AP_HAL_ChibiOS_K3/hwdef/boot/ipc_ring.h](libraries/AP_HAL_ChibiOS_K3/hwdef/boot/ipc_ring.h)).
Adres: `0xA1120000` (64 KiB), R5F→Host veri `0x1000` ofsetinde (8 KiB),
Host→R5F veri `0x3000` ofsetinde (8 KiB).

Bunu QGroundControl'e (UDP 14550) köprülemek için host'ta iki script çalışır
([deploy/host/](deploy/host/)):

- **`gem_mavbridge.py`** — kartta çalışır (host'tan SSH ile başlatılır),
  `/dev/mem` üzerinden mmap ile ring'i okur/yazar, stdin/stdout üzerinden
  host'a ham byte akışı verir.
- **`run_bridge.py`** — host'ta çalışır, SSH ile `gem_mavbridge.py`'yi
  başlatır, stdout'unu UDP 14550'ye, QGC'den gelen UDP'yi de stdin'e
  yönlendirir. Bağlantı koparsa (reboot vs.) otomatik yeniden dener.

Host'ta `systemd --user` servisi olarak kurulur
([deploy/systemd-host/gem-mavbridge.service](deploy/systemd-host/gem-mavbridge.service) —
`ExecStart` yolunu kendi `run_bridge.py` konumunuza göre düzenleyin):

```sh
mkdir -p ~/.config/systemd/user
cp deploy/systemd-host/gem-mavbridge.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now gem-mavbridge
loginctl enable-linger "$USER"   # oturum kapansa da servis çalışmaya devam etsin
```

**`/dev/mem` hizalama kuralı**: bu board'da `/dev/mem` üzerinden bu
"reserved" bellek bölgelerine erişirken her okuma/yazmanın başlangıcı VE
bitişi 8 byte'a hizalı olmak zorunda, yoksa gerçek bir SIGBUS ile process
çöküyor (glibc'nin `memcpy`'si sınırda örtüşen bir kuyruk yüklemesi yapıyor,
Device-tipi bellekte bu gerçek donanım hatasına yol açıyor). `gem_mavbridge.py`
ve `gem_storaged.py`'deki `read_aligned()`/`write_aligned()` bunu hallediyor —
bu board'da `/dev/mem` ile yapılacak her işte bu kurala uyulmalı.

## Doğrulama

```sh
# R5F kendi firmware'ini otomatik yüklüyor mu:
sshpass -p gem ssh gemstone@192.168.7.2 "cat /sys/class/remoteproc/remoteproc2/state /sys/class/remoteproc/remoteproc2/firmware"
# -> "running" ve "j722s-mcu-r5f0_0-fw"

# arducopter/Linux gerçekten kapalı mı:
sshpass -p gem ssh gemstone@192.168.7.2 "systemctl is-active arducopter; systemctl is-enabled arducopter"
# -> inactive / disabled

# 3 board-native servis çalışıyor mu:
sshpass -p gem ssh gemstone@192.168.7.2 "systemctl is-active chibios-spi-release chibios-pwm-clocks gem-storaged"

# Host'taki köprü servisi çalışıyor mu:
systemctl --user is-active gem-mavbridge

# QGroundControl'ü açın (UDP 14550'yi dinler, özel ayar gerekmez) —
# "Not Ready" / "Stabilize" + ArduPilot logosu görünmeli.
```

## Bilinen kısıtlamalar (2026-08-18 itibarıyla)

- **GPS çalışmıyor.** Linux/ArduCopter kurulumunda GPS `UART-MAIN6` (Main
  domain UART, `/dev/ttyS6`/`SERIAL3`) üzerinden geliyordu. R5F, MCU
  domain'de — bu UART'a fiziksel olarak erişemiyor; `AP_HAL_ChibiOS_K3`'te
  `serial1`-`serial9` hepsi boş/sahte sürücü. GPS gerektiren modlar (Auto,
  Guided, RTL, PosHold) kullanılamaz, sadece Stabilize/Acro gibi GPS'siz
  modlar mümkün.
- **IMU 100Hz'e sabit** → `SCHED_LOOP_RATE=50` şart. `AP_InertialSensor_ICM20948_K3.cpp`'de
  IMU okuma hızı bilinçli olarak 100Hz'e sabitlenmiş (daha hızlı bir 14-byte
  block-read yöntemi her eksenin yüksek byte'inda 1 bit sessizce bozuk veri
  döndürüyordu). ArduCopter'ın varsayılan 400Hz döngü hızını karşılayamıyor,
  "Main loop slow"/"Gyro rate" prearm hatalarına yol açıyor. `SCHED_LOOP_RATE`
  parametresini MAVLink `PARAM_SET` ile `50` yapın (reboot gerekir).
- **`ARMING_CHECK` parametresi yok**, QGC "Missing params" uyarısı veriyor —
  bug değil, ArduPilot'un kendi kaynağında çok yeni bir isim değişikliği
  (`ARMING_CHECK` → ters mantıklı `ARMING_SKIPCHK`); QGC'nin dahili listesi
  henüz güncel değil. Zararsız, arm/uçuşu engellemiyor.
- **Her firmware değişikliğinde tam reboot şart** — `am67_mailbox.h` zaten
  var ama build `mailbox_init()` çağırmıyor; `RP_MBOX_SHUTDOWN`'a cevap
  verilse `"stop"` sorunsuz çalışır, reboot'a gerek kalmazdı (ileride
  düzeltilebilir).
- **`trace0` debugfs sınırlı** — 16 KiB, dairesel değil; büyük miktarda veri
  için değil, sadece insan-okur tanısal loglama için kullanışlı.

## Depo yapısı

```
.                          ArduPilot kaynağı (emirhan-sonmez/ardupilot @ gemstone-o1-r5f-hal)
├── libraries/AP_HAL_ChibiOS_K3/   R5F için özel HAL backend
├── modules/ChibiOS-Gemstone-O1-Port/   ChibiOS portu (emirhan-sonmez/ChibiOS-Gemstone-O1-Port @ gemstone-o1-r5f)
└── deploy/                 Karta/host'a kurulan, hiçbir kaynak repoda olmayan parçalar
    ├── board/gem_storaged.py
    ├── host/gem_mavbridge.py, run_bridge.py
    ├── systemd-board/       3 board-native servis
    └── systemd-host/        host'taki systemd --user servisi
```

Orijinal ArduPilot projesi hakkında: [README_ARDUPILOT.md](README_ARDUPILOT.md).
