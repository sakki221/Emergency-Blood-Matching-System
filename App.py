from flask import Flask, request, jsonify, render_template
from collections import defaultdict
import heapq
import uuid
import datetime
import urllib.parse
import os

app = Flask(__name__)

# ==================== DATA STRUCTURES ====================
donors_by_blood_group = defaultdict(list)
emergency_requests = []
emergency_counter = [0]
matching_history = []

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
    
    if not all_compatible_donors:
        return None, None, f"No donors found for compatible blood types: {', '.join(compatible_types)}"
    
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
        return None, None, f"Found {len(all_compatible_donors)} donor(s) but none are eligible (90-day waiting period)"

def initialize_sample_data():
    """Initialize sample donors - called on startup"""
    sample_donors = [
        {'name': 'John Doe', 'blood_group': 'O-', 'location': 'Hospital A', 'last_donation_date': '2024-08-01'},
        {'name': 'Jane Smith', 'blood_group': 'O+', 'location': 'Hospital B', 'last_donation_date': '2024-08-15'},
        {'name': 'Bob Johnson', 'blood_group': 'A+', 'location': 'Hospital C', 'last_donation_date': '2024-07-20'},
        {'name': 'Alice Williams', 'blood_group': 'B-', 'location': 'Hospital D', 'last_donation_date': '2024-08-10'},
        {'name': 'Charlie Brown', 'blood_group': 'AB+', 'location': 'Hospital A', 'last_donation_date': '2024-08-01'},
        {'name': 'David Miller', 'blood_group': 'O-', 'location': 'Hospital C', 'last_donation_date': '2024-07-15'},
        {'name': 'Emma Davis', 'blood_group': 'A-', 'location': 'Hospital B', 'last_donation_date': '2024-07-20'},
        {'name': 'Frank Wilson', 'blood_group': 'B+', 'location': 'Hospital D', 'last_donation_date': '2024-08-01'},
        {'name': 'Grace Lee', 'blood_group': 'O+', 'location': 'Hospital A', 'last_donation_date': '2024-07-25'},
        {'name': 'Henry Taylor', 'blood_group': 'A+', 'location': 'Hospital B', 'last_donation_date': '2024-08-05'},
    ]
    
    for donor_data in sample_donors:
        blood_group = normalize_blood_group(donor_data['blood_group'])
        donor = {
            'id': str(uuid.uuid4()),
            'name': donor_data['name'],
            'blood_group': blood_group,
            'location': donor_data['location'],
            'last_donation_date': donor_data['last_donation_date'],
            'total_donations': 0
        }
        donors_by_blood_group[blood_group].append(donor)
    
    print(f"✓ Initialized {len(sample_donors)} sample donors")

# ==================== API ENDPOINTS ====================

@app.route('/')
def home():
    return render_template('frontend.html')

@app.route('/admin')
def admin():
    return render_template('admin.html')

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint for Render"""
    total_donors = sum(len(donors) for donors in donors_by_blood_group.values())
    return jsonify({
        'status': 'healthy',
        'total_donors': total_donors,
        'emergency_queue_size': len(emergency_requests),
        'timestamp': datetime.datetime.now().isoformat()
    }), 200

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
        
        # Validate location
        if data['location'] not in LOCATIONS:
            return jsonify({'error': f'Invalid location. Must be one of: {", ".join(LOCATIONS.keys())}'}), 400
        
        # Create donor record
        donor = {
            'id': str(uuid.uuid4()),
            'name': data['name'],
            'blood_group': blood_group,
            'location': data['location'],
            'last_donation_date': data['last_donation_date'],
            'total_donations': 0
        }
        
        donors_by_blood_group[blood_group].append(donor)
        
        return jsonify({
            'message': 'Donor added successfully',
            'donor': donor
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/donors', methods=['GET'])
def get_all_donors():
    """Get all donors"""
    all_donors = []
    for blood_group, donors in donors_by_blood_group.items():
        all_donors.extend(donors)
    
    return jsonify({
        'total_donors': len(all_donors),
        'donors': all_donors
    }), 200

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
    
    # ✅ UPDATE: Mark donor as recently donated instead of removing
    donor['last_donation_date'] = datetime.datetime.now().strftime('%Y-%m-%d')
    donor['total_donations'] = donor.get('total_donations', 0) + 1
    
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
        'distance_km': distance,
        'message': 'Donor matched successfully! They will be eligible again after 90 days.'
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
        
        # Validate urgency level
        if not isinstance(urgency, int) or urgency < 1 or urgency > 5:
            return jsonify({'error': 'urgency_level must be an integer between 1-5'}), 400
        
        # Add to emergency queue with timestamp
        request_id = str(uuid.uuid4())
        request_data = {
            'id': request_id,
            'patient': patient,
            'timestamp': datetime.datetime.now().isoformat()
        }
        
        # Use counter as tiebreaker (lower urgency = higher priority)
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
        # Pop highest priority request (Min-Heap)
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
        
        # ✅ UPDATE: Mark donor as recently donated instead of removing
        donor['last_donation_date'] = datetime.datetime.now().strftime('%Y-%m-%d')
        donor['total_donations'] = donor.get('total_donations', 0) + 1
        
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
            'remaining_requests': len(emergency_requests),
            'donor_message': 'Donor will be eligible again after 90 days'
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
            'eligible': eligible,
            'not_eligible': len(donors) - eligible
        }
    
    return jsonify(stats)

@app.route('/api/matching-history', methods=['GET'])
def get_matching_history():
    """Get all matching history"""
    formatted_matches = []
    for match in matching_history:
        formatted_match = {
            'match_id': str(uuid.uuid4()),
            'timestamp': match['timestamp'],
            'match_type': match['type'],
            'urgency_level': match.get('urgency', 'N/A'),
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
        'matches': list(reversed(formatted_matches))
    })

# ==================== INITIALIZATION ====================

# Initialize sample data when app starts
initialize_sample_data()

if __name__ == '__main__':
    print("=" * 60)
    print("🩸 Blood Donor Matching System Started")
    print("=" * 60)
    total_donors = sum(len(donors) for donors in donors_by_blood_group.values())
    print(f"✓ Total donors in system: {total_donors}")
    print("✓ Main Interface: http://localhost:5000/")
    print("✓ Admin Panel: http://localhost:5000/admin")
    print("✓ Health Check: http://localhost:5000/api/health")
    print("=" * 60)
    
    # Get port from environment variable for Render deployment
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
