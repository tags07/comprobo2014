#!/usr/bin/env python

""" This code implements a ceiling-marker based localization system.
    The core of the code is filling out the marker_locators
    which allow for the specification of the position and orientation
    of the markers on the ceiling of the room """

import rospy
from ar_pose.msg import ARMarkers
from tf.transformations import euler_from_quaternion, rotation_matrix, quaternion_from_matrix, quaternion_from_euler
import numpy as np
from geometry_msgs.msg import PoseStamped, Pose, Point, Quaternion
from std_msgs.msg import Header
from tf import TransformListener, TransformBroadcaster
from copy import deepcopy
from math import sin, cos, pi

class TransformHelpers:
    """ Some convenience functions for translating between various representions of a robot pose.
        TODO: nothing... you should not have to modify these """

    @staticmethod
    def convert_translation_rotation_to_pose(translation, rotation):
        """ Convert from representation of a pose as translation and rotation (Quaternion) tuples to a geometry_msgs/Pose message """
        return Pose(position=Point(x=translation[0],y=translation[1],z=translation[2]), orientation=Quaternion(x=rotation[0],y=rotation[1],z=rotation[2],w=rotation[3]))

    @staticmethod
    def convert_pose_inverse_transform(pose):
        """ Helper method to invert a transform (this is built into the tf C++ classes, but ommitted from Python) """
        translation = np.zeros((4,1))
        translation[0] = -pose.position.x
        translation[1] = -pose.position.y
        translation[2] = -pose.position.z
        translation[3] = 1.0

        rotation = (pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w)
        euler_angle = euler_from_quaternion(rotation)
        rotation = np.transpose(rotation_matrix(euler_angle[2], [0,0,1]))       # the angle is a yaw
        transformed_translation = rotation.dot(translation)

        translation = (transformed_translation[0], transformed_translation[1], transformed_translation[2])
        rotation = quaternion_from_matrix(rotation)
        return (translation, rotation)

class MarkerLocator(object):
    def __init__(self, id, position, yaw):
        """ Create a MarkerLocator object
            id: the id of the marker (this is an index based on the file
                specified in ar_pose_multi.launch)
            position: this is a tuple of the x,y position of the marker
            yaw: this is the angle about a normal vector pointed towards
                 the STAR center ceiling
        """
        self.id = id
        self.position = position
        self.yaw = yaw

    def get_camera_position(self, marker):
        """ Outputs the position of the camera in the global coordinates """
        euler_angles = euler_from_quaternion((marker.pose.pose.orientation.x,
                                              marker.pose.pose.orientation.y,
                                              marker.pose.pose.orientation.z,
                                              marker.pose.pose.orientation.w))
        translation = np.array([marker.pose.pose.position.y,
                                -marker.pose.pose.position.x,
                                0,
                                1.0])
        translation_rotated = rotation_matrix(self.yaw-euler_angles[2], [0,0,1]).dot(translation)
        xy_yaw = (translation_rotated[0]+self.position[0],translation_rotated[1]+self.position[1],self.yaw-euler_angles[2])
        return xy_yaw

class MarkerProcessor(object):
    def __init__(self):
        rospy.init_node('star_center_positioning_node')
        self.marker_sub = rospy.Subscriber("ar_pose_marker",
                                           ARMarkers,
                                           self.process_markers)
        self.star_pose_pub = rospy.Publisher("STAR_pose",PoseStamped,queue_size=10)
        self.star_pose_offset_pub = rospy.Publisher("STAR_pose_corrected",PoseStamped,queue_size=10)
        self.tf_listener = TransformListener()
        self.tf_broadcaster = TransformBroadcaster()
        self.marker_locators = {}
        self.marker_locators[1] = MarkerLocator(1,(0.0,0.0),0)

    def process_markers(self, msg):
        for marker in msg.markers:
            if marker.id in self.marker_locators:
                locator = self.marker_locators[marker.id]
                xy_yaw = locator.get_camera_position(marker)
                orientation_tuple = quaternion_from_euler(0,0,xy_yaw[2])
                pose = Pose(position=Point(x=xy_yaw[0],y=xy_yaw[1],z=0),
                            orientation=Quaternion(x=orientation_tuple[0], y=orientation_tuple[1], z=orientation_tuple[2], w=orientation_tuple[3]))
                # TODO: use markers timestamp instead of now() (unfortunately, not populated currently by ar_pose)
                pose_stamped = PoseStamped(header=Header(stamp=rospy.Time.now(),frame_id="STAR"),pose=pose)
                try:
                    offset, quaternion = self.tf_listener.lookupTransform("/base_link", "/base_laser_link", rospy.Time(0))
                except Exception as inst:
                    print "Error", inst
                    return
                # TODO: use frame timestamp instead of now()
                pose_stamped_corrected = deepcopy(pose_stamped)
                pose_stamped_corrected.pose.position.x -= offset[0]*cos(xy_yaw[2])
                pose_stamped_corrected.pose.position.y -= offset[0]*sin(xy_yaw[2])
                self.star_pose_offset_pub.publish(pose_stamped_corrected)
                self.star_pose_pub.publish(pose_stamped)
                self.fix_STAR_to_odom_transform(pose_stamped_corrected)

    def fix_STAR_to_odom_transform(self, msg):
        """ Super tricky code to properly update map to odom transform... do not modify this... Difficulty level infinity. """
        (translation, rotation) = TransformHelpers.convert_pose_inverse_transform(msg.pose)
        p = PoseStamped(pose=TransformHelpers.convert_translation_rotation_to_pose(translation,rotation),header=Header(stamp=rospy.Time(),frame_id="base_link"))
        try:
            self.tf_listener.waitForTransform("odom","base_link",rospy.Time(),rospy.Duration(1.0))
        except Exception as inst:
            print "whoops", inst
            return
        print "got transform"
        self.odom_to_STAR = self.tf_listener.transformPose("odom", p)
        (self.translation, self.rotation) = TransformHelpers.convert_pose_inverse_transform(self.odom_to_STAR.pose)

    def broadcast_last_transform(self):
        """ Make sure that we are always broadcasting the last map to odom transformation.
            This is necessary so things like move_base can work properly. """
        if not(hasattr(self,'translation') and hasattr(self,'rotation')):
            return
        self.tf_broadcaster.sendTransform(self.translation, self.rotation, rospy.get_rostime(), "odom", "STAR")

    def run(self):
        r = rospy.Rate(10)
        while not rospy.is_shutdown():
            self.broadcast_last_transform()
            r.sleep()

if __name__ == '__main__':
    nh = MarkerProcessor()
    nh.run()