from flask import Flask, request, jsonify, render_template
from collections import defaultdict
import heapq
import uuid
import datetime
import urllib.parse

app = Flask(__name__)

# ==================== DATA STRUCTURES ====================
donors_by_blood_group = defaultdict(list)
emergency_requests = []
emergency_counter = [0]
matching_history = []  # Track all matches

# Blood compatibility: Who can receive from whom
BLOOD_COMPATIBILITY = {
    'O-': ['O-'],
    'O+': ['O-', 'O+'],
    'A-': ['O-', 'A-'],
    'A+': ['O-', 'O+', 'A-', 'A+'],
    'B-': ['O-', 'B-'],
    'B+': ['O-', 'O+', 'B-', 'B+'],
    'AB-': ['O-', 'A-', 'B-', 'AB-'],
    'AB+': ['O-', 'O+', 'A-', 'A+', 'B-', 'B+', 'AB-', 'AB+']
}

# Location graph: distances between locations in km
LOCATIONS = {
    'Hospital A': {'Hospital B': 15, 'Hospital C': 25, 'Hospital D': 35, 'Hospital A': 0},
    'Hospital B': {'Hospital A': 15, 'Hospital C': 8, 'Hospital D': 10, 'Hospital B': 0},
    'Hospital C': {'Hospital A': 25, 'Hospital B': 8, 'Hospital D': 30, 'Hospital C': 0},
    'Hospital D': {'Hospital A': 35, 'Hospital B': 10, 'Hospital C': 30, 'Hospital D': 0}
}

# ==================== HELPER FUNCTIONS ====================

def normalize_blood_group(bg):
    """Normalize blood group format"""
    bg = urllib.parse.unquote(bg)
    bg = bg.strip().upper().replace(' ', '')
    return bg

def is_donor_eligible(donor):
    """Check if donor is eligible (90 days since last donation)"""
    try:
        last_donation = datetime.datetime.strptime(donor['last_donation_date'], '%Y-%m-%d')
        today = datetime.datetime.now()
        days_since_donation = (today - last_donation).days
        return days_since_donation >= 90
    except (ValueError, KeyError):
        return False

def calculate_distance(from_location, to_location):
    """Calculate shortest distance between two locations using Dijkstra's algorithm"""
    if from_location not in LOCATIONS or to_location not in LOCATIONS:
        return float('inf')
    
    # Dijkstra's algorithm
    distances = {loc: float('inf') for loc in LOCATIONS}
    distances[from_location] = 0
    pq = [(0, from_location)]
    visited = set()
    
    while pq:
        current_dist, current_loc = heapq.heappop(pq)
        
        if current_loc in visited:
            continue
        visited.add(current_loc)
        
        if current_loc == to_location:
            return current_dist
        
        for neighbor, weight in LOCATIONS.get(current_loc, {}).items():
            new_dist = current_dist + weight
            if new_dist < distances[neighbor]:
                distances[neighbor] = new_dist
                heapq.heappush(pq, (new_dist, neighbor))
    
    return distances.get(to_location, float('inf'))

def find_nearest_donor(patient_blood_group, patient_location):
    """Find the nearest eligible donor for a patient"""
    patient_blood_group = normalize_blood_group(patient_blood_group)
    
    if patient_blood_group not in BLOOD_COMPATIBILITY:
        return None, None, "Invalid blood group"
    
    # Get compatible donor blood types
    compatible_types = BLOOD_COMPATIBILITY[patient_blood_group]
    
    # Collect all compatible donors
    all_compatible_donors = []
    for blood_type in compatible_types:
        all_compatible_donors.extend(donors_by_blood_group.get(blood_type, []))
    
    # Filter eligible donors and find nearest
    best_donor = None
    min_distance = float('inf')
    
    for donor in all_compatible_donors:
        if is_donor_eligible(donor):
            distance = calculate_distance(patient_location, donor['location'])
            if distance < min_distance:
                min_distance = distance
                best_donor = donor
    
    if best_donor:
        return best_donor, min_distance, None
    else:
        return None, None, "No eligible donor found"

# ==================== API ENDPOINTS ====================

@app.route('/')
def home():
    return render_template('frontend.html')

@app.route('/admin')
def admin():
    return render_template('admin.html')

@app.route('/api/donors', methods=['POST'])
def add_donor():
    """Add a new donor"""
    try:
        data = request.json
        
        # Validate required fields
        required_fields = ['name', 'blood_group', 'location', 'last_donation_date']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Normalize and validate blood group
        blood_group = normalize_blood_group(data['blood_group'])
        if blood_group not in BLOOD_COMPATIBILITY:
            return jsonify({'error': 'Invalid blood group'}), 400
        
        # Create donor record
        donor = {
            'id': str(uuid.uuid4()),
            'name': data['name'],
            'blood_group': blood_group,
            'location': data['location'],
            'last_donation_date': data['last_donation_date']
        }
        
        donors_by_blood_group[blood_group].append(donor)
        
        return jsonify({
            'message': 'Donor added successfully',
            'donor': donor
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/donors/search', methods=['GET'])
def search_donors():
    """Search donors by blood group"""
    blood_group = request.args.get('blood_group')
    
    if not blood_group:
        return jsonify({'error': 'blood_group parameter required'}), 400
    
    blood_group = normalize_blood_group(blood_group)
    donors = donors_by_blood_group.get(blood_group, [])
    
    return jsonify(donors)

@app.route('/api/match', methods=['GET'])
def match_donor():
    """Find best donor match for a patient"""
    blood_group = request.args.get('blood_group')
    location = request.args.get('location')
    
    if not blood_group or not location:
        return jsonify({'error': 'blood_group and location parameters required'}), 400
    
    donor, distance, error = find_nearest_donor(blood_group, location)
    
    if error:
        return jsonify({'error': error}), 404
    
    # Remove donor from pool
    donor_blood_group = donor['blood_group']
    donors_by_blood_group[donor_blood_group].remove(donor)
    
    # Track match
    matching_history.append({
        'timestamp': datetime.datetime.now().isoformat(),
        'type': 'Normal',
        'patient_blood': normalize_blood_group(blood_group),
        'patient_location': location,
        'donor_name': donor['name'],
        'donor_blood': donor['blood_group'],
        'donor_location': donor['location'],
        'distance_km': distance
    })
    
    return jsonify({
        'match_found': True,
        'donor': donor,
        'distance_km': distance
    })

@app.route('/api/emergency', methods=['POST'])
def emergency_request():
    """Add emergency blood request to priority queue"""
    try:
        data = request.json
        urgency = data.get('urgency_level', 1)
        patient = data.get('patient', {})
        
        # Validate patient data
        if not patient.get('blood_group') or not patient.get('location'):
            return jsonify({'error': 'Patient blood_group and location required'}), 400
        
        # Add to emergency queue with timestamp
        request_id = str(uuid.uuid4())
        request_data = {
            'id': request_id,
            'patient': patient,
            'timestamp': datetime.datetime.now().isoformat()
        }
        
        # Use counter as tiebreaker
        emergency_counter[0] += 1
        heapq.heappush(emergency_requests, (urgency, emergency_counter[0], request_data))
        
        return jsonify({
            'message': 'Emergency request added to queue',
            'request_id': request_id,
            'urgency_level': urgency,
            'position_in_queue': len(emergency_requests)
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/emergency/process', methods=['POST'])
def process_next_emergency():
    """Process the next emergency request from priority queue"""
    if not emergency_requests:
        return jsonify({'error': 'No emergency requests in queue'}), 404
    
    try:
        # Pop highest priority request
        urgency, counter, request_data = heapq.heappop(emergency_requests)
        patient = request_data['patient']
        
        # Find match
        donor, distance, error = find_nearest_donor(
            patient.get('blood_group'),
            patient.get('location')
        )
        
        if error:
            return jsonify({
                'message': 'Emergency request processed but no match found',
                'request': request_data,
                'urgency_level': urgency,
                'error': error,
                'match_found': False,
                'remaining_requests': len(emergency_requests)
            }), 200
        
        # Remove donor from pool
        donor_blood_group = donor['blood_group']
        donors_by_blood_group[donor_blood_group].remove(donor)
        
        # Track match
        matching_history.append({
            'timestamp': datetime.datetime.now().isoformat(),
            'type': 'Emergency',
            'urgency': urgency,
            'patient_blood': patient.get('blood_group'),
            'patient_location': patient.get('location'),
            'donor_name': donor['name'],
            'donor_blood': donor['blood_group'],
            'donor_location': donor['location'],
            'distance_km': distance
        })
        
        return jsonify({
            'message': 'Emergency request processed successfully',
            'request': request_data,
            'urgency_level': urgency,
            'match_found': True,
            'donor': donor,
            'distance_km': distance,
            'remaining_requests': len(emergency_requests)
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/emergency/queue', methods=['GET'])
def view_emergency_queue():
    """View all emergency requests in queue"""
    try:
        if not emergency_requests:
            return jsonify({
                'message': 'No emergency requests in queue',
                'total_requests': 0,
                'queue': []
            }), 200
        
        # Create a copy to view without modifying the heap
        queue_copy = sorted(emergency_requests, key=lambda x: (x[0], x[1]))
        
        queue_data = [{
            'urgency_level': urgency,
            'request': request_data
        } for urgency, counter, request_data in queue_copy]
        
        return jsonify({
            'total_requests': len(emergency_requests),
            'queue': queue_data
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get donor statistics"""
    stats = {}
    for blood_group in BLOOD_COMPATIBILITY.keys():
        donors = donors_by_blood_group.get(blood_group, [])
        eligible = sum(1 for d in donors if is_donor_eligible(d))
        stats[blood_group] = {
            'total': len(donors),
            'eligible': eligible
        }
    
    return jsonify(stats)

@app.route('/api/matching-history', methods=['GET'])
def get_matching_history():
    """Get all matching history with proper format for admin panel"""
    # Format matches for admin panel
    formatted_matches = []
    for match in matching_history:
        formatted_match = {
            'match_id': str(uuid.uuid4()),  # Generate unique ID for each match
            'timestamp': match['timestamp'],
            'match_type': match['type'],  # 'Normal' or 'Emergency'
            'urgency_level': match.get('urgency', 'N/A'),  # Only for emergency
            'patient': {
                'blood_group': match['patient_blood'],
                'location': match['patient_location']
            },
            'donor': {
                'name': match['donor_name'],
                'blood_group': match['donor_blood'],
                'location': match['donor_location']
            },
            'distance_km': match['distance_km']
        }
        formatted_matches.append(formatted_match)
    
    return jsonify({
        'total_matches': len(formatted_matches),
        'matches': list(reversed(formatted_matches))  # Most recent first
    })

if __name__ == '__main__':
    # Add some sample donors
    sample_donors = [
        {'name': 'John Doe', 'blood_group': 'O-', 'location': 'Hospital A', 'last_donation_date': '2025-01-01'},
        {'name': 'Jane Smith', 'blood_group': 'O+', 'location': 'Hospital B', 'last_donation_date': '2025-02-15'},
        {'name': 'Bob Johnson', 'blood_group': 'A+', 'location': 'Hospital C', 'last_donation_date': '2025-03-20'},
        {'name': 'Alice Williams', 'blood_group': 'B-', 'location': 'Hospital D', 'last_donation_date': '2025-01-10'},
        {'name': 'Charlie Brown', 'blood_group': 'AB+', 'location': 'Hospital A', 'last_donation_date': '2025-02-01'},
        {'name': 'David Miller', 'blood_group': 'O-', 'location': 'Hospital C', 'last_donation_date': '2025-01-15'},
        {'name': 'Emma Davis', 'blood_group': 'A-', 'location': 'Hospital B', 'last_donation_date': '2025-02-20'},
        {'name': 'Frank Wilson', 'blood_group': 'B+', 'location': 'Hospital D', 'last_donation_date': '2025-03-01'},
    ]
    
    for donor_data in sample_donors:
        blood_group = normalize_blood_group(donor_data['blood_group'])
        donor = {
            'id': str(uuid.uuid4()),
            'name': donor_data['name'],
            'blood_group': blood_group,
            'location': donor_data['location'],
            'last_donation_date': donor_data['last_donation_date']
        }
        donors_by_blood_group[blood_group].append(donor)
    
    print("=" * 60)
    print("🩸 Blood Donor Matching System Started")
    print("=" * 60)
    print(f"Sample donors added: {len(sample_donors)}")
    print("Main Interface: http://localhost:5000/")
    print("Admin Panel: http://localhost:5000/admin")
    print("=" * 60)
    
    app.run(debug=True, host='0.0.0.0', port=5000)