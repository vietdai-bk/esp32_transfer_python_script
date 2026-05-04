## Scripts dùng để truyền ảnh sang ESP32 để thực hiện dự doán và nhận lại kết quả
1. Clone script này về máy
```
git clone https://github.com/vietdai-bk/esp32_transfer_python_script
```
2. Cài đặt các thư viện
```
pip install requests opencv-python
```
3. Cập nhật địa chỉ IP được log ra từ ESP32 ở file ```send_one_image.py```
```
ESP32_IP = "192.168.1.6"
```
4. Chạy test với một ảnh
```
python send_one_image.py /path/to/image.png
```
5. Chạy với một folder ảnh (thực tế tại Vòng Chung Kết)  
***Cập nhật lại đường dẫn tới folder, ip của esp32***, thực hiện chạy lệnh sau:
```
python main.py
```
Kết quả lưu tại ```results.csv```, các đội thi nộp lại file này về cho BTC tại ngày chung kết để tính điểm.
