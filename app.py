from flask import Flask, render_template, request, redirect, session, url_for, send_from_directory
from flask_mysqldb import MySQL
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import razorpay
import os

app = Flask(__name__)

# ========================
# SECURITY CONFIG
# ========================
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key")

# ========================
# MYSQL CONFIG (ENV BASED)
# ========================
app.config['MYSQL_HOST'] = os.getenv('MYSQL_HOST', 'localhost')
app.config['MYSQL_USER'] = os.getenv('MYSQL_USER', 'root')
app.config['MYSQL_PASSWORD'] = os.getenv('MYSQL_PASSWORD', '9044')
app.config['MYSQL_DB'] = os.getenv('MYSQL_DB', 'vehicle_rental')

mysql = MySQL(app)

# ========================
# RAZORPAY CONFIG
# ========================
razorpay_client = razorpay.Client(
    auth=(
        os.getenv("RAZORPAY_KEY_ID"),
        os.getenv("RAZORPAY_KEY_SECRET")
    )
)

# ========================
# FILE UPLOAD CONFIG
# ========================
UPLOAD_FOLDER = os.path.join(app.root_path, 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)




mysql = MySQL(app)

# Home
@app.route('/')
def home():
    return redirect('/login')

# Register
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = generate_password_hash(request.form['password'])

        cur = mysql.connection.cursor()
        cur.execute(
            "INSERT INTO users (username, email, password) VALUES (%s, %s, %s)",
            (username, email, password)
        )
        mysql.connection.commit()
        cur.close()

        return redirect('/login')

    return render_template('register.html')

# Login
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cur.fetchone()
        cur.close()

        if user and check_password_hash(user[3], password):
            session['user_id'] = user[0]
            session['username'] = user[1]
            return redirect('/dashboard')
        else:
            return "Invalid username or password"

    return render_template('login.html')

# Dashboard
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect('/login')

    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT 
            v.*,
            ROUND(AVG(r.rating), 1) AS avg_rating,
            COUNT(r.id) AS review_count,
            MAX(
                CASE 
                    WHEN b.status='Approved' AND b.end_date >= CURDATE()
                    THEN 1 ELSE 0
                END
            ) AS is_booked
        FROM vehicles v
        LEFT JOIN reviews r ON v.id = r.vehicle_id
        LEFT JOIN bookings b ON v.id = b.vehicle_id
        GROUP BY v.id
        ORDER BY v.id DESC
    """)
    vehicles = cur.fetchall()
    cur.close()

    return render_template('dashboard.html', vehicles=vehicles)



@app.route('/book/<int:vehicle_id>', methods=['POST'])
def book_vehicle(vehicle_id):
    if 'user_id' not in session:
        return redirect('/login')

    start_date = request.form['start_date']
    end_date = request.form['end_date']

    cur = mysql.connection.cursor()

    # Check for overlapping approved bookings
    cur.execute("""
        SELECT * FROM bookings
        WHERE vehicle_id = %s
        AND status = 'Approved'
        AND (
            (%s BETWEEN start_date AND end_date)
            OR
            (%s BETWEEN start_date AND end_date)
            OR
            (start_date BETWEEN %s AND %s)
        )
    """, (vehicle_id, start_date, end_date, start_date, end_date))

    conflict = cur.fetchone()

    if conflict:
        cur.close()
        return "Vehicle already booked for selected dates!"
        cur.execute("""
        SELECT 1 FROM bookings
        WHERE vehicle_id=%s
        AND status='Approved'
        AND end_date >= CURDATE()
    """, (vehicle_id,))
    if cur.fetchone():
        cur.close()
        return "Vehicle currently unavailable."

    # If no conflict, insert booking
    cur.execute("""
        INSERT INTO bookings (vehicle_id, user_id, start_date, end_date, status)
        VALUES (%s, %s, %s, %s, %s)
    """, (vehicle_id, session['user_id'], start_date, end_date, 'Pending'))

    mysql.connection.commit()
    cur.close()

    return redirect('/dashboard')

@app.route('/owner_bookings')
def owner_bookings():
    if 'user_id' not in session:
        return redirect('/login')

    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT 
            b.id,
            v.name,
            u.username,
            b.start_date,
            b.end_date,
            b.status,
            b.payment_status
        FROM bookings b
        JOIN vehicles v ON b.vehicle_id = v.id
        JOIN users u ON b.user_id = u.id
        WHERE v.owner_id = %s
        ORDER BY b.id DESC
    """, (session['user_id'],))

    bookings = cur.fetchall()
    cur.close()

    return render_template('owner_bookings.html', bookings=bookings)


@app.route('/update_booking/<int:booking_id>', methods=['POST'])
def update_booking(booking_id):
    if 'user_id' not in session:
        return redirect('/login')

    action = request.form['action']

    cur = mysql.connection.cursor()
    cur.execute("""
        UPDATE bookings
        SET status = %s
        WHERE id = %s
    """, (action, booking_id))
    mysql.connection.commit()
    cur.close()

    return redirect('/owner_bookings')

@app.route('/my_bookings')
def my_bookings():
    if 'user_id' not in session:
        return redirect('/login')

    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT 
            b.id,              -- b[0] booking_id (USED FOR PAYMENT)
            v.name,            -- b[1]
            v.image,           -- b[2]
            v.location,        -- b[3]
            v.price_per_day,   -- b[4]
            b.start_date,      -- b[5]
            b.end_date,        -- b[6]
            b.status,          -- b[7]
            b.payment_status   -- b[8]
        FROM bookings b
        JOIN vehicles v ON b.vehicle_id = v.id
        WHERE b.user_id = %s
        ORDER BY b.id DESC
    """, (session['user_id'],))

    bookings = cur.fetchall()
    cur.close()

    return render_template('my_bookings.html', bookings=bookings)


@app.route('/vehicle/<int:vehicle_id>')
def vehicle_detail(vehicle_id):
    cur = mysql.connection.cursor()

    # Vehicle
    cur.execute("SELECT * FROM vehicles WHERE id=%s", (vehicle_id,))
    vehicle = cur.fetchone()

    # Reviews
    cur.execute("""
        SELECT r.rating, r.comment, u.username
        FROM reviews r
        JOIN users u ON r.user_id = u.id
        WHERE r.vehicle_id=%s
        ORDER BY r.created_at DESC
    """, (vehicle_id,))
    reviews = cur.fetchall()

    # Average rating
    cur.execute("""
        SELECT ROUND(AVG(rating), 1)
        FROM reviews WHERE vehicle_id=%s
    """, (vehicle_id,))
    avg_rating = cur.fetchone()[0]

    cur.close()

    return render_template(
        'vehicle_detail.html',
        vehicle=vehicle,
        reviews=reviews,
        avg_rating=avg_rating
    )

@app.route('/review/<int:vehicle_id>', methods=['POST'])
def submit_review(vehicle_id):
    if 'user_id' not in session:
        return redirect('/login')

    rating = int(request.form['rating'])
    comment = request.form['comment']

    cur = mysql.connection.cursor()

    # Check if user has an APPROVED booking for this vehicle
    cur.execute("""
        SELECT 1 FROM bookings
        WHERE vehicle_id=%s AND user_id=%s AND status='Approved'
    """, (vehicle_id, session['user_id']))
    eligible = cur.fetchone()

    if not eligible:
        cur.close()
        return "You can review only after an approved booking."

    # Insert review
    try:
        cur.execute("""
            INSERT INTO reviews (vehicle_id, user_id, rating, comment)
            VALUES (%s, %s, %s, %s)
        """, (vehicle_id, session['user_id'], rating, comment))
        mysql.connection.commit()
    except:
        cur.close()
        return "You already reviewed this vehicle."

    cur.close()
    return redirect(f'/vehicle/{vehicle_id}')

@app.route('/pay/<int:booking_id>')
def pay(booking_id):
    print("PAY ROUTE HIT, booking_id =", booking_id)
    if 'user_id' not in session:
        return redirect('/login')

    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT b.id, v.price_per_day, DATEDIFF(b.end_date, b.start_date)+1
        FROM bookings b
        JOIN vehicles v ON b.vehicle_id = v.id
        WHERE b.id=%s AND b.user_id=%s AND b.status='Approved'
    """, (booking_id, session['user_id']))

    booking = cur.fetchone()
    if not booking:
        cur.close()
        return "Invalid booking"

    total_amount = booking[1] * booking[2] * 100  # in paise

    order = razorpay_client.order.create({
        "amount": total_amount,
        "currency": "INR",
        "payment_capture": 1
    })
    print("RAZORPAY ORDER:", order)

    cur.execute("""
        UPDATE bookings SET razorpay_order_id=%s
        WHERE id=%s
    """, (order['id'], booking_id))
    mysql.connection.commit()
    cur.close()

    return render_template(
        'pay.html',
        order=order,
        amount=total_amount,
        booking_id=booking_id,
        key="rzp_test_SHyVKTDtFJLXmT"
    )

@app.route('/payment_success', methods=['POST'])
def payment_success():
    data = request.get_json()

    cur = mysql.connection.cursor()
    cur.execute("""
        UPDATE bookings
        SET payment_status='Paid',
            razorpay_payment_id=%s
        WHERE id=%s AND razorpay_order_id=%s
    """, (
        data['razorpay_payment_id'],
        data['booking_id'],
        data['razorpay_order_id']
    ))
    mysql.connection.commit()
    cur.close()

    return "OK"



# Logout
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@app.route('/add_vehicle', methods=['GET', 'POST'])
def add_vehicle():
    if 'user_id' not in session:
        return redirect('/login')

    if request.method == 'POST':
        name = request.form['name']
        vtype = request.form['type']
        price = request.form['price']
        location = request.form['location']
        image = request.files['image']

        filename = secure_filename(image.filename)
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        image.save(image_path)

        cur = mysql.connection.cursor()
        cur.execute("""
            INSERT INTO vehicles (owner_id, name, type, price_per_day, location, image)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (session['user_id'], name, vtype, price, location, filename))
        mysql.connection.commit()
        cur.close()

        return redirect('/dashboard')

    return render_template('add_vehicle.html')

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)