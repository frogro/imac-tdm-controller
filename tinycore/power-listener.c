/* Linux input listener for our HID System Power Down device. */
#include <linux/input.h>
#include <sys/ioctl.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <stdlib.h>

int main(void) {
    int fds[64];
    for (int i = 0; i < 64; i++) fds[i] = -1;
    for (;;) {
        for (int i = 0; i < 64; i++) {
            if (fds[i] < 0) {
                char path[64], name[256] = {0};
                struct input_id id;
                snprintf(path, sizeof(path), "/dev/input/event%d", i);
                int fd = open(path, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
                if (fd < 0) continue;
                if (ioctl(fd, EVIOCGID, &id) < 0 || ioctl(fd, EVIOCGNAME(sizeof(name)), name) < 0 ||
                    id.bustype != BUS_USB || id.vendor != 0x1d6b || id.product != 0x0104 ||
                    !strstr(name, "iMac TDM Controller")) {
                    close(fd);
                    continue;
                }
                fds[i] = fd;
            }
            struct input_event event;
            ssize_t n;
            while ((n = read(fds[i], &event, sizeof(event))) == sizeof(event)) {
                if (event.type == EV_KEY && event.code == KEY_POWER && event.value == 1) {
                    puts("HID power key: shutting down");
                    fflush(stdout);
                    execl("/sbin/poweroff", "poweroff", (char *)NULL);
                    perror("poweroff");
                    return 1;
                }
            }
            if (n == 0 || (n < 0 && errno != EAGAIN && errno != EINTR)) {
                close(fds[i]);
                fds[i] = -1;
            }
        }
        usleep(100000);
    }
}
