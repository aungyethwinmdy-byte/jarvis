# Cell 2: cloudflared (tunnel) — internet ကနေ ဒီ server ကို ခေါ်နိုင်အောင်
!wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -O /tmp/cloudflared
!chmod +x /tmp/cloudflared
print("cloudflared ready")
