import cv2
import time

# Try multiple indexes (0, 1, 2)
for index in range(3):
    print(f"🔍 Trying camera index {index}...")
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    time.sleep(2)

    if cap.isOpened():
        print(f"✅ Camera index {index} opened")

        ret, frame = cap.read()
        if ret:
            print("✅ Successfully read a frame")
            cv2.imshow("Webcam Test", frame)
            cv2.waitKey(0)
            cv2.destroyAllWindows()
            break
        else:
            print("❌ Failed to read frame")
        cap.release()
    else:
        print(f"❌ Camera index {index} not available")

