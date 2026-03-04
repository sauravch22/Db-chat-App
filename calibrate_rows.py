"""Quick script to calibrate expected row counts for new test queries."""
import httpx

EXECUTE_URL = "http://localhost:8000/api/chat/execute"
CID = 3

def run(name, sql):
    try:
        r = httpx.post(EXECUTE_URL, json={"connection_id": CID, "sql": sql}, timeout=15.0).json()
        if r.get("success"):
            print(f"{name}: {r['row_count']} rows")
        else:
            print(f"{name}: ERR - {r.get('error', '?')[:80]}")
    except Exception as e:
        print(f"{name}: EXC - {e}")

run("employees_with_mgr",
    "SELECT e.employee_id, e.first_name, m.first_name AS mgr FROM employee e JOIN employee m ON e.reports_to = m.employee_id")
run("tracks_over_5min",
    "SELECT track_id, name FROM track WHERE milliseconds > 300000")
run("customers_usa",
    "SELECT customer_id, first_name, last_name FROM customer WHERE country = 'USA'")
run("invoices_2025",
    "SELECT invoice_id FROM invoice WHERE EXTRACT(YEAR FROM invoice_date) = 2025")
run("genre_revenue",
    "SELECT genre.name, SUM(invoice_line.unit_price * invoice_line.quantity) AS rev FROM genre JOIN track ON genre.genre_id = track.genre_id JOIN invoice_line ON track.track_id = invoice_line.track_id GROUP BY genre.name ORDER BY rev DESC")
run("top3_genres_tracks",
    "SELECT genre.name, COUNT(track.track_id) AS cnt FROM genre JOIN track ON genre.genre_id = track.genre_id GROUP BY genre.name ORDER BY cnt DESC LIMIT 3")
run("customers_no_invoice",
    "SELECT c.customer_id FROM customer c LEFT JOIN invoice i ON c.customer_id = i.customer_id WHERE i.invoice_id IS NULL")
run("avg_invoice_country",
    "SELECT billing_country, AVG(total) FROM invoice GROUP BY billing_country")
run("tracks_never_sold",
    "SELECT t.track_id FROM track t LEFT JOIN invoice_line il ON t.track_id = il.track_id WHERE il.invoice_line_id IS NULL")
run("top10_artists_albums",
    "SELECT artist.name, COUNT(album.album_id) AS cnt FROM artist JOIN album ON artist.artist_id = album.artist_id GROUP BY artist.artist_id, artist.name ORDER BY cnt DESC LIMIT 10")
run("employee_cust_count",
    "SELECT e.first_name, e.last_name, COUNT(c.customer_id) FROM employee e JOIN customer c ON e.employee_id = c.support_rep_id GROUP BY e.employee_id, e.first_name, e.last_name")
run("country_above_avg",
    "SELECT billing_country, SUM(total) AS ct FROM invoice GROUP BY billing_country HAVING SUM(total) > (SELECT AVG(ct) FROM (SELECT SUM(total) AS ct FROM invoice GROUP BY billing_country) sub)")
run("genre_above_avg_tracks",
    "SELECT genre.name, COUNT(track.track_id) AS tc FROM genre JOIN track ON genre.genre_id = track.genre_id GROUP BY genre.genre_id, genre.name HAVING COUNT(track.track_id) > (SELECT AVG(gc) FROM (SELECT COUNT(track_id) AS gc FROM track WHERE genre_id IS NOT NULL GROUP BY genre_id) sub)")
run("longest_album",
    "SELECT album.title, SUM(track.milliseconds) AS ms FROM album JOIN track ON album.album_id = track.album_id GROUP BY album.album_id, album.title ORDER BY ms DESC LIMIT 1")
run("rock_tracks_count",
    "SELECT COUNT(*) FROM track JOIN genre ON track.genre_id = genre.genre_id WHERE genre.name = 'Rock'")
run("customer_invoice_count_top10",
    "SELECT c.first_name, c.last_name, COUNT(i.invoice_id) AS inv_cnt FROM customer c JOIN invoice i ON c.customer_id = i.customer_id GROUP BY c.customer_id, c.first_name, c.last_name ORDER BY inv_cnt DESC LIMIT 10")
